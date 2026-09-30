import os

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

    assert result["outcome"] == "captured", result["failure"]
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
