import base64
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("STOLOSIO_E2E") != "1",
        reason="set STOLOSIO_E2E=1 with the Docker Compose stack running",
    ),
]
API = os.getenv("STOLOSIO_E2E_HTTP_URL", "http://localhost:8411")
HTML_ONLY = ["text/html", "application/xhtml+xml", "application/xml", "text/xml"]


def capture(**body) -> dict:
    response = httpx.post(f"{API}/v1/capture", json=body, timeout=180)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_page_is_captured_through_the_egress_proxy_and_the_local_fleet() -> None:
    result = capture(url="https://example.com/", accept=HTML_ONLY, reference="e2e-capture")

    assert result["outcome"] == "captured", json.dumps(result)["failure"]
    assert result["reference"] == "e2e-capture"
    assert result["document"]["media_type"] == "text/html"
    assert [a["tier"] for a in result["evidence"]["attempts"]][:1] == ["direct"]


def test_a_redirect_into_an_exclusion_fails_as_excluded() -> None:
    result = capture(url="http://www.github.com/", exclusions=[{"host": "github.com"}])

    assert result["outcome"] == "failed"
    assert result["failure"]["code"] == "excluded" and result["document"] is None


def test_an_unaccepted_media_type_fails_without_a_body() -> None:
    result = capture(
        url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        accept=HTML_ONLY,
    )

    assert result["failure"]["code"] == "unsupported_media_type"
    assert result["document"] is None


@pytest.fixture(scope="module")
def local_challenge_site():
    """Temporary origin on a Docker-only public-address subnet: egress policy stays intact."""
    network = f"stolosio-challenge-e2e-{uuid4().hex[:8]}"
    container = network + "-origin"
    connected = []

    def docker(*args):
        return subprocess.check_output(["docker", *args], text=True).strip()

    # Special-use IPs are intentionally refused by the real egress firewall. This subnet
    # exists only inside Docker; fixture traffic cannot leave it. No firewall is relaxed.
    docker("network", "create", "--subnet", "11.254.254.0/24", network)
    try:
        docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--network",
            network,
            "--ip",
            "11.254.254.2",
            "--network-alias",
            "stolosio-challenge-origin",
            "--mount",
            f"type=bind,src={Path(__file__).with_name('challenge_origin.py').resolve()},dst=/origin.py,readonly",
            "python:3.13-alpine",
            "python",
            "/origin.py",
        )
        for service in ("fetch-proxy", "browserless"):
            target = docker("compose", "ps", "--quiet", service)
            assert target, f"Compose {service} must be running"
            docker("network", "connect", network, target)
            connected.append(target)
        yield "http://stolosio-challenge-origin"
    finally:
        for target in connected:
            subprocess.run(["docker", "network", "disconnect", network, target], check=False)
        subprocess.run(["docker", "rm", "--force", container], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)


@pytest.mark.parametrize("allow_paid", [False, True])
def test_local_resolution_clears_a_browser_challenge_without_paid_fallback(
    local_challenge_site, allow_paid
):
    origin = local_challenge_site
    result = capture(url=f"{origin}/clears/{uuid4().hex}", resolve_bot_challenges=allow_paid)
    assert result["outcome"] == "captured", json.dumps(result)
    assert [a["tier"] for a in result["evidence"]["attempts"]] == ["direct", "local_resolution"]
    assert not result["evidence"]["cost"]["paid"]
    assert result["evidence"]["cost"]["browser_seconds"] > 0
    assert result["evidence"]["attempts"][-1]["decision"] == "accept"
    body = base64.b64decode(result["document"]["body_base64"]).decode()
    assert "Local resolution demonstration" in body and "Section 11" in body
    print(
        json.dumps(
            {
                "outcome": result["outcome"],
                "allow_paid": allow_paid,
                "tiers": [a["tier"] for a in result["evidence"]["attempts"]],
                "cost": result["evidence"]["cost"],
            }
        )
    )


def test_local_resolution_reports_a_persistent_challenge_without_paid_permission(
    local_challenge_site,
):
    origin = local_challenge_site
    result = capture(url=f"{origin}/holds/{uuid4().hex}")
    assert result["outcome"] == "failed", result
    assert result["failure"]["code"] == "bot_challenge", json.dumps(result)
    assert result["failure"]["resolution_attempted"]
    assert [a["tier"] for a in result["evidence"]["attempts"]] == ["direct", "local_resolution"]
    assert not result["evidence"]["cost"]["paid"]
