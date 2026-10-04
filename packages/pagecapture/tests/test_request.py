"""Schema v2 requests: exclusions, accept and validation (docs/api.md)."""

import pytest

from pagecapture import CaptureRequest, Exclusion
from pagecapture.render.adaptive import exclusion_fetch_patterns


def request(**fields):
    return CaptureRequest.from_json({"url": "https://example.test/page", **fields})


def test_defaults_accept_any_media_type_and_exclude_nothing():
    r = request()
    assert r.exclusions == () and r.accept is None and r.resolve_bot_challenges is False


def test_exclusions_and_accept_are_normalized():
    r = request(
        exclusions=[{"host": "Ads.Example.COM."}, {"host": "*.tracker.test", "path_prefix": "/a/../pixel"}],
        accept=["Text/HTML", "application/xml", "text/html"],
    )
    assert r.exclusions == (Exclusion("ads.example.com", "/"), Exclusion("*.tracker.test", "/pixel"))
    assert r.accept == ("text/html", "application/xml")


@pytest.mark.parametrize(
    "fields",
    [
        {"url": "ftp://example.test/"},
        {"url": "https:///nohost"},
        {"unknown": 1},
        {"resolve_bot_challenges": "yes"},
        {"exclusions": [{"host": "bad host"}]},
        {"exclusions": [{"host": "example.test", "path_prefix": "no-slash"}]},
        {"exclusions": [{"host": "example.test", "path_prefix": "/a?b"}]},
        {"exclusions": [{"host": "example.test", "extra": 1}]},
        {"exclusions": {"host": "example.test"}},
        {"accept": []},
        {"accept": ["html"]},
        {"deadline_ms": 0},
        {"deadline_ms": True},
        {"reference": 5},
    ],
)
def test_invalid_requests_are_rejected(fields):
    with pytest.raises(ValueError):
        CaptureRequest.from_json({"url": "https://example.test/page", **fields})


def test_an_excluded_url_is_an_invalid_request():
    with pytest.raises(ValueError, match="excluded"):
        request(exclusions=[{"host": "example.test", "path_prefix": "/page"}])


@pytest.mark.parametrize(
    "host,path,url,expected",
    [
        ("example.test", "/", "https://example.test/anything", True),
        ("example.test", "/", "https://sub.example.test/", False),
        ("*.example.test", "/", "https://example.test/", True),
        ("*.example.test", "/", "https://a.b.example.test/x", True),
        ("*.example.test", "/", "https://notexample.test/", False),
        ("*", "/private", "https://any.test/private/x", True),
        ("example.test", "/admin", "https://example.test/admin", True),
        ("example.test", "/admin", "https://example.test/admin/users", True),
        ("example.test", "/admin", "https://example.test/administrator", False),
        ("example.test", "/admin", "https://example.test/x/../admin/", True),
        ("example.test", "/admin", "https://example.test/%61dmin", True),
    ],
)
def test_exclusions_match_hosts_and_whole_path_segments(host, path, url, expected):
    assert Exclusion.from_json({"host": host, "path_prefix": path}).matches(url) is expected


def test_exclusions_become_fetch_patterns_that_cover_them():
    patterns = exclusion_fetch_patterns(
        (Exclusion("*.example.test", "/"), Exclusion("*", "/admin"), Exclusion("ads.test", "/x"))
    )
    assert patterns == ["*://*.example.test*", "*://*/admin*", "*://ads.test*", "*://example.test*"]
def test_structured_suffix_accept_ranges_are_validated_and_match_only_their_family():
    from pagecapture.api import CaptureRequest, accepts

    request = CaptureRequest.from_json({"url": "https://example.test/", "accept": ["application/*+json"]})
    assert accepts(request.accept, "application/vnd.api+json")
    assert not accepts(request.accept, "text/vnd.api+json")
    assert not accepts(request.accept, "application/json")
    assert not accepts(request.accept, "application/+json")
    global_range = CaptureRequest.from_json({"url": "https://example.test/", "accept": ["*/*+json"]})
    assert accepts(global_range.accept, "model/gltf+json")
    assert accepts(global_range.accept, "application/ld+json")
    assert not accepts(global_range.accept, "application/json")
    assert not accepts(global_range.accept, "application/pdf")
