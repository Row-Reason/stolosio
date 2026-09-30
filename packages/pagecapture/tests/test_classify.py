"""Fast unit tests on hand-made responses (no network)."""

import requests
from requests.structures import CaseInsensitiveDict

from pagecapture.classify import rules
from pagecapture.classify.classifier import Classifier
from pagecapture.config import Settings
from pagecapture.document import Document, word_count
from pagecapture.fetch import Fetched


def response(
    body: str | bytes,
    status: int = 200,
    headers: dict | None = None,
    url: str = "https://example.com/page",
    history: list | None = None,
) -> requests.Response:
    r = requests.Response()
    r.status_code, r.url = status, url
    r._content = body.encode() if isinstance(body, str) else body
    r.headers = CaseInsensitiveDict({"Content-Type": "text/html; charset=utf-8", **(headers or {})})
    r.history = history or []
    return r


def classifier() -> Classifier:
    return Classifier(Settings())


def test_word_count_counts_cjk_by_pairs():
    assert word_count("hello world") == 2
    assert word_count("日本語のテキスト") == 4


def test_unreachable_exits_without_parsing():
    v = classifier().classify(Fetched("https://nx.invalid/", None, "ConnectionError"))
    assert v.rejected and v.reason == "unreachable" and list(v.flags) == ["unreachable"]


def test_pdf_is_payload_mismatch():
    v = classifier().classify(
        Fetched("https://example.com/a.pdf", response(b"%PDF-1.7", headers={"Content-Type": "application/pdf"}), None)
    )
    assert v.reason == "payload_mismatch"


def test_challenge_header_exits_before_parsing():
    doc = Document("https://example.com/", response("<html></html>", 403, {"cf-mitigated": "challenge"}))
    flags, stopped = rules.evaluate(doc, stop_confidence=0.9)
    assert stopped and flags["bot_challenge"].value
    assert "soup" not in doc.__dict__  # the HTML was never parsed


def test_bare_403_is_client_error_not_challenge():
    doc = Document(
        "https://example.com/", response("<html><title>403 Forbidden</title><h1>403 Forbidden</h1>nginx</html>", 403)
    )
    flags, _ = rules.evaluate(doc)
    assert flags["client_error"].value and not flags["bot_challenge"].value


def test_login_redirect_is_auth():
    hop = response("", 302, url="https://example.com/account")
    doc = Document(
        "https://example.com/account",
        response("<form><input type=password></form>", url="https://example.com/login", history=[hop]),
    )
    flags, _ = rules.evaluate(doc)
    assert flags["auth"].value


def test_hidden_streamed_text_counts_as_present():
    html = "<main><div class=skeleton></div></main><div hidden id='S:0'>" + "real words " * 50 + "</div>"
    doc = Document("https://example.com/", response(html))
    assert doc.stats.hidden_words == 100 and doc.words == 100


def test_block_pages_are_told_from_challenges():
    blocked = Document(
        "https://example.com/",
        response(
            "<html><head><title>Attention Required! | Cloudflare</title></head>"
            "<body><h1>Sorry, you have been blocked</h1></body></html>",
            status=403,
        ),
    )
    assert rules.block_page(blocked) == "block page: you have been blocked"
    challenge = Document(
        "https://example.com/",
        response(
            "<html><head><title>Just a moment...</title><script>window._cf_chl_opt={}</script></head>"
            "<body>Verify you are human</body></html>",
            status=403,
        ),
    )
    assert rules.block_page(challenge) is None


def test_site_own_captcha_page_is_a_challenge():
    doc = Document(
        "https://example.com/",
        response(
            '<html><body><form method="post"><font>Please confirm that you are a human visitor.<br>'
            "Enter the given number code and click 'OK'.</font>"
            '<img src="/code.png"><input name="code"></form></body></html>'
        ),
    )
    assert rules.bot_challenge(doc, {}).value


def test_declarative_shadow_dom_text_counts_as_content():
    html = (
        '<html><body><vt-app><template shadowrootmode="open"><h1>Analyse suspicious files</h1>'
        "<p>and URLs to detect types of malware</p></template></vt-app><template><p>inert</p></template></body></html>"
    )
    doc = Document("https://example.com/", response(html))
    assert "analyse suspicious files" in doc.stats.text and "inert" not in doc.stats.text


def moved(requested: str, final: str) -> Document:
    history = [response("", 301, {"Location": final}, url=requested)]
    return Document(
        requested,
        response("<html><title>Home</title><body>" + "word " * 400 + "</body></html>", url=final, history=history),
    )


def test_deep_link_to_another_sites_front_page_is_a_soft_404_unless_it_moved_to_its_own_domain():
    assert rules.not_found(moved("https://old.example.com/race/49/2013/", "https://newsite.com/"), {}).value
    assert not rules.not_found(
        moved("https://www.mozilla.org/en-US/firefox/", "https://www.firefox.com/en-US/"), {}
    ).value


def test_empty_directory_listing_is_parked():
    doc = Document(
        "https://example.com/",
        response(
            "<html><head><title>Index of /</title></head><body><h1>Index of /</h1>"
            "<pre>Name Last modified Size cgi-bin/ 2020-11-23</pre></body></html>"
        ),
    )
    assert rules.parked(doc, {}).value


def test_listing_with_free_and_paid_items_is_not_a_paywall():
    ld = '<script type="application/ld+json">[{"isAccessibleForFree":true},{"isAccessibleForFree":false}]</script>'
    doc = Document(
        "https://example.com/", response(f"<html><head>{ld}</head><body><h1>Events</h1><p>Meetup</p></body></html>")
    )
    assert not rules.paywall(doc, {}).value


def test_server_default_page_is_parked():
    doc = Document(
        "https://example.com/",
        response(
            "<html><head><title>Domain Default page</title></head><body>"
            "<p>This is a default webpage generated for by Plesk.</p></body></html>"
        ),
    )
    assert rules.parked(doc, {}).value
