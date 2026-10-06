"""Hand-written rules for every column where rules are reliable and should hold on unseen sites:
status codes, payload types, bot-protection fingerprints, redirects and explicit wording.

Rules run in the priority order of docs/labels.md. Each returns a Flag with a fixed confidence reflecting how reliable
that signal was on the audited data. Status, header and redirect rules never parse the HTML, so certain rejections
found by them cost almost nothing.
"""

import re
from collections.abc import Callable

from ..document import Document
from ..labels import Flag

RATE_PHRASES = ("too many requests", "rate limit", "request rate", "rate threshold")
CHALLENGE_TITLES = (
    "just a moment",
    "attention required! | cloudflare",
    "vercel security checkpoint",
    "client challenge",
    "access denied",
    "access to this page has been denied",
    "are you a robot",
    "bot or not",
    "human verification",
    "security check",
    "security verification",
    "checking your browser",
    "making sure you're not a bot",
    "please hold a moment",
    "it needs a human touch",
    "not to be a robot",
    "verifying your browser",
    "checking connection",
    "waf forbidden",
)
# Visible text that marks a rendered page as an interactive challenge (for comparing and benchmarking renders)
CHALLENGE_TEXT = (
    "just a moment",
    "checking your browser",
    "verify you are human",
    "security verification",
    "are you a robot",
    "security service to protect",
)
CHALLENGE_MARKUP = (
    "cf_chl_opt",
    "awswafintegration",
    "px-captcha",
    "captcha-delivery.com",
    "_____tmd_____/punish",
    "_wafchallengeid",
    "sec-cpt",
)  # ("sec-container" is a common CSS class: dell.com, bing.com)
CHALLENGE_PHRASES = (
    "please enable js and disable any ad blocker",
    "you have been blocked",
    "ip address is blocked",
    "unusual traffic",
    "verify you are human",
    "not a robot",
    "security service to protect",
    "you don't have permission to access",
    "waf forbidden",
    "verifying your browser",
    "anubis",
    "that you are not a bot",
    "if you are not a bot",
    "complete the security check",
    "access from ip address",
    "cookies must be enabled",
    "vérification de sécurité",
    "verificación de seguridad",
    "sicherheitsüberprüfung",
    "verifica di sicurezza",
    "the request could not be satisfied",
    "incapsula incident id",
    "request unsuccessful",
    "unable to give you access",
    "problem providing the content you requested",
    "accesso negato",
    "acceso bloqueado",
    "confirm that you are a human",
    "confirm you are a human",
    "complete the following challenge",
    "complete the challenge below",
)
GEO_PHRASES = (
    "not available in your country",
    "not yet available in your country",
    "unavailable in your country",
    "not available in your region",
    "unavailable in your location",
    "not available in your location",
    "only accessible from",
    "only available from",
    "can only be accessed from",
    "not accessible from your country",
    "in ihrem land nicht verfügbar",
    "in ihrer region nicht verfügbar",
    "aus deutschland aufrufbar",
    "pas disponible dans votre pays",
    "pas disponible dans votre région",
    "no está disponible en tu país",
    "no está disponible en su país",
    "non è disponibile nel tuo paese",
    "não está disponível no seu país",
    "お住まいの地域ではご利用いただけません",
    "您所在的地区",
    "您所在的国家",
    "недоступен в вашей стране",
)
BROWSER_PHRASES = (
    "browser not supported",
    "browser is not supported",
    "browser isn't supported",
    "unsupported browser",
    "unsupported client",
    "not supported on your browser",
    "isn't supported on your browser",
    "browser version isn't supported",
    "update your browser",
    "upgrade your browser",
    "browser is deprecated",
    "isn't compatible with",
    "not optimized for your browser",
    "requires an up-to-date browser",
    "incompatible browser",
    "isn't supported on your device",
    "not supported on your device",
    "not supported on this device",
)
PAYWALL_PHRASES = (
    "this post is for paid subscribers",
    "subscribe to read",
    "subscribe to continue",
    "to continue reading",
    "subscriber-only",
    "subscribers only",
    "unlock this article",
    "keep reading with a",
    "stat+",
)
PAYWALL_STRONG = (
    "this post is for paid subscribers",
    "subscribe to continue reading",
    "subscribe to read the full",
    "有料登録すると続き",
    "続きをお読みいただけます",
    "réservé aux abonnés",
    "exclusivo para suscriptores",
    "exclusivo para assinantes",
    "riservato agli abbonati",
    "nur für abonnenten",
    "付费阅读",
    "订阅后阅读",
)
PARKED_PHRASES = (
    "domain is for sale",
    "domain may be for sale",
    "domain for sale",
    "buy this domain",
    "this domain is parked",
    "domain parking",
    "parked free",
    "parked domain",
    "is coming soon",
    "this domain is managed at",
)
# web servers' own default pages: a domain with no site on it
SERVER_DEFAULT_PAGES = (
    "domain default page",
    "default webpage generated",
    "default web page for this domain",
    "apache2 ubuntu default page",
    "apache2 debian default page",
    "welcome to nginx!",
    "test page for the apache",
    "test page for the nginx",
    "future home of something quite cool",
    "this site is currently under construction",
)
SERVER_DEFAULT_TITLES = SERVER_DEFAULT_PAGES + ("iis windows server", "it works!")  # too common as body text
PARKED_MARKUP = ("sedoparking", "parkingcrew", "bodis.com", "afternic", "hugedomains", "dan.com/", "namebright")
REQUEST_FAILED_PHRASES = (
    "request couldn't be processed",
    "request could not be processed",
    "couldn't process your request",
    "could not process your request",
)
MAINTENANCE_PHRASES = (
    "under maintenance",
    "down for maintenance",
    "scheduled maintenance",
    "temporarily unavailable",
    "extended downtime",
    "working to restore",
    "we'll be back soon",
    "we will be back soon",
    "en maintenance",
    "en mantenimiento",
    "wartungsarbeiten",
    "in manutenzione",
    "em manutenção",
    "メンテナンス中",
    "维护中",
    "維護中",
    "технические работы",
)
QUEUE_PHRASES = ("waiting room", "you are now in line", "routing to checkout", "queue-it")
STUB_OPENINGS = ("continue to", "transferring to", "redirecting to", "you are being redirected", "redirecting...")
AGE_GATE_PHRASES = (
    "adult only",
    "adults only",
    "are you over 18",
    "are you 18",
    "i am over 18",
    "i am 18 or older",
    "you must be 18",
    "you must be at least 18",
    "age verification",
    "confirm your age",
    "verify your age",
    "enter your date of birth",
)
PICKER_PHRASES = ("choose a country", "choose your country", "select your country", "select country")
LOGIN_PHRASES = ("you have to be logged in", "sign in to continue", "log in to continue", "please log in")
LOGIN_TITLES = ("sign in", "sign-in", "log in", "login", "log-in", "signin")
OAUTH_BUTTONS = (
    "continue with google",
    "continue with apple",
    "continue with facebook",
    "continue with microsoft",
    "sign in with google",
    "sign in with apple",
    "log in with google",
    "log in with apple",
)
NOT_FOUND_PHRASES = (
    "page not found",
    "not found",
    "cannot be found",
    "can't be found",
    "no such",
    "doesn't exist",
    "does not exist",
    "error 404",
    "could not be found",
    "couldn't be found",
)
GONE_PHRASES = (
    "no longer available",
    "has been removed",
    "has been deleted",
    "was removed",
    "was deleted",
    "permanently removed",
    "content removed",
    "this page has been retired",
    "has been discontinued",
    "service has ended",
    "サービス終了",
    "提供を終了",
    "服务已停止",
    "停止服务",
    "서비스 종료",
    "dienst wurde eingestellt",
    "service a été arrêté",
    "servicio ha finalizado",
)
FORBIDDEN_PATH = re.compile(r"/(403|access[-_]denied|forbidden)(\b|[-_/])", re.I)
ENABLE_COOKIES = re.compile(r"enable[-_ ]cookies|cookies[-_ ]required", re.I)


def has(haystack: str, phrases) -> bool:
    return any(p in haystack for p in phrases)


def yes(confidence: float, detail: str) -> Flag:
    return Flag(True, confidence, "rule", detail)


def no(doc: Document, *, parsed: bool = True) -> Flag:
    """No rule fired. Small pages are where block and error pages hide, so a "no" there is less sure."""
    return Flag(False, 1.0 if not parsed else (0.9 if doc.small else 0.95), "rule")


# ---- one function per column, in priority order ------------------------------------------------------------


def payload_mismatch(doc: Document, found: dict) -> Flag:
    if doc.status < 400 and not doc.is_markup:
        return yes(0.95, f"content type {doc.content_type}")
    if 200 <= doc.status < 300 and doc.empty_body:
        return yes(0.9, "empty body")
    return Flag(False, 1.0, "rule")


def challenge_header(doc: Document) -> str | None:
    """Bot-protection vendors mark challenge/block responses with headers that never occur on normal pages."""
    h = doc.headers
    if h.get("cf-mitigated") == "challenge":
        return "cf-mitigated: challenge"
    if "x-vercel-mitigated" in h:
        return "x-vercel-mitigated"
    if h.get("x-amzn-waf-action") in ("challenge", "captcha", "block"):
        return f"x-amzn-waf-action: {h['x-amzn-waf-action']}"
    if doc.status >= 400 and ("x-datadome" in h or "x-dd-b" in h or h.get("server") == "datadome"):
        return "DataDome block"
    if doc.status == 403 and h.get("server", "").startswith("akamaighost"):
        return "Akamai 403"
    return None


BLOCK_PHRASES = (
    "you have been blocked",
    "ip address is blocked",
    "your ip has been blocked",
    "access denied",
    "request unsuccessful. incapsula incident",
    "waf forbidden",
    "error 1020",
    "error 1005",
    "you don't have permission to access",
)


# Markup of challenges a real browser (or a provider's solver) can pass
INTERACTIVE_MARKUP = ("cf_chl_opt", "captcha-delivery.com", "px-captcha", "awswafintegration", "_incapsula_resource")
BLOCK_HEADERS = ("x-amzn-waf-action: block", "Akamai 403")  # challenge_header() results that are refusals


def block_page(doc: Document) -> str | None:
    """A bot-protection page that refuses this client outright (IP or fingerprint reputation), as opposed to a
    challenge a real browser can pass. Solving captchas doesn't help here; only a different identity (a proxy) might."""
    if doc.small and has(doc.text, ("botstopper", "anubis")) and "access denied" in doc.text:
        return "block page: bot protection access denied"
    header = challenge_header(doc)
    if header in BLOCK_HEADERS:
        return header
    if any(m in doc.markup for m in INTERACTIVE_MARKUP):
        return None  # an interactive challenge is on the page
    phrase = next((p for p in BLOCK_PHRASES if p in doc.text or p in doc.title), None)
    return f"block page: {phrase}" if phrase else None


def bot_challenge(doc: Document, found: dict) -> Flag:
    header = challenge_header(doc)
    if header:
        return yes(0.99, header)
    if doc.small and has(doc.text, ("botstopper", "anubis")) and "access denied" in doc.text:
        return yes(0.99, "bot protection access denied")
    # A bare "403 Forbidden" page without challenge or block wording is only client_error.
    if (
        has(doc.title, CHALLENGE_TITLES)
        or ((doc.small or doc.status >= 400) and has(doc.markup, CHALLENGE_MARKUP))
        or (doc.small and has(doc.text, CHALLENGE_PHRASES))
        or (doc.status != 200 and doc.words < 50 and (doc.js_notice or "cookies" in doc.text))
    ):
        return yes(0.95, "challenge page markers")
    return no(doc)


def rate_limited(doc: Document, found: dict) -> Flag:
    if doc.status == 429:
        return yes(1.0, "HTTP 429")
    if challenge_header(doc):
        return no(doc, parsed=False)  # non-429 challenge headers can reject without parsing HTML
    if doc.small and has(doc.text, RATE_PHRASES):
        return yes(0.75, "rate limit message")
    return no(doc)


def geo_blocked(doc: Document, found: dict) -> Flag:
    if doc.status == 451:
        return yes(1.0, "HTTP 451")
    # block pages often keep the site's navigation, so phrases also count when only <main> is thin
    thin_main = doc.small or (doc.stats.main_words is not None and doc.stats.main_words < 100)
    if "unavailable-in-your-location" in doc.resp.url or (thin_main and has(doc.text, GEO_PHRASES)):
        return yes(0.85, "not available in this region")
    return no(doc)


def unsupported_browser(doc: Document, found: dict) -> Flag:
    if (
        doc.words < 120 and has(doc.text + " " + doc.title, BROWSER_PHRASES)
    ) or "unsupported" in doc.final.path.lower():
        return yes(0.85, "unsupported browser message")
    return no(doc)


def interstitial(doc: Document, found: dict) -> Flag:
    text = doc.text + " " + doc.title
    if "<frameset" in doc.markup:
        return yes(0.9, "frameset")
    if doc.redirected and (ENABLE_COOKIES.search(doc.final.path) or ENABLE_COOKIES.search(doc.title)):
        return yes(0.85, f"redirected to a cookies-required page ({doc.final.path})")
    if doc.small and has(text, QUEUE_PHRASES):
        return yes(0.85, "queue / waiting room")
    if doc.small and ("before you continue" in doc.text or doc.final.netloc.startswith("consent.")):
        return yes(0.8, "consent wall")
    # a challenge page's own redirect script isn't a stub in front of the real page
    # (an app shell's bootstrap script can redirect too: an empty mount point means it's the app, not a stub)
    if (
        not found.get("bot_challenge", no(doc)).value
        and doc.words < 15
        and not doc.empty_mount
        and (doc.meta_refresh or doc.js_redirect or doc.text.startswith(STUB_OPENINGS))
    ):
        return yes(0.75, "redirect stub")
    if doc.small and has(text, AGE_GATE_PHRASES):
        return yes(0.75, "age gate")
    if doc.words < 400 and has(text, PICKER_PHRASES):
        return yes(0.7, "country picker")
    return no(doc)


def auth(doc: Document, found: dict) -> Flag:
    if doc.redirected_to_login:
        return yes(0.9, f"redirected to {doc.final.path}")
    login_title = has(doc.title, ("log in", "login", "sign in", "sign-in"))
    if doc.redirected and doc.same_site and re.sub(r"[^a-z -]", "", doc.title).strip() in LOGIN_TITLES:
        return yes(0.85, f"redirected to a sign-in page ({doc.final.path})")
    if doc.small and (has(doc.text, LOGIN_PHRASES) or (doc.password_inputs and (doc.words < 120 or login_title))):
        return yes(0.8, "login form on a small page")
    if doc.words < 150 and sum(p in doc.text for p in OAUTH_BUTTONS) >= 2:
        return yes(0.75, "sign-in buttons on a small page")
    if doc.status == 401:
        return yes(0.6, "HTTP 401")
    return no(doc)


def paywall(doc: Document, found: dict) -> Flag:
    if doc.status == 402:
        return yes(1.0, "HTTP 402 Payment Required")
    # (a page that also declares free items is a listing of mixed items, e.g. an event calendar, not a paywall)
    if (
        re.search(r'"isaccessibleforfree"\s*:\s*"?false', doc.markup)
        and not re.search(r'"isaccessibleforfree"\s*:\s*"?true', doc.markup)
        and (has(doc.text, PAYWALL_PHRASES) or doc.stats.body_words < 400)
    ):
        return yes(0.85, "isAccessibleForFree: false with a teaser or subscription wording")
    if has(doc.text, PAYWALL_STRONG) and doc.stats.body_words < 600:
        return yes(0.8, "short article with 'subscribe to keep reading' wording")
    return no(doc)


def parked(doc: Document, found: dict) -> Flag:
    if doc.small and (has(doc.text + " " + doc.title, PARKED_PHRASES) or has(doc.markup, PARKED_MARKUP)):
        return yes(0.85, "parked / for-sale domain")
    if doc.words < 15 and doc.lander_redirect:
        return yes(0.8, "script redirect to /lander (domain-parking pattern)")
    if doc.title.startswith("index of /") and doc.words < 60:
        return yes(0.8, "an empty directory listing instead of a site")
    if doc.small and (
        has(doc.title, SERVER_DEFAULT_TITLES) or (doc.words < 60 and has(doc.text, SERVER_DEFAULT_PAGES))
    ):
        return yes(0.8, "the web server's default page: no site on this domain")
    return no(doc)


def gone(doc: Document, found: dict) -> Flag:
    if doc.status == 410:
        return yes(1.0, "HTTP 410")
    if doc.status != 404 and doc.small and doc.words < 150 and has(doc.text + " " + doc.title, GONE_PHRASES):
        return yes(0.75, "page says the content was removed")
    return no(doc)


def not_found(doc: Document, found: dict) -> Flag:
    if doc.status == 404:
        return yes(1.0, "HTTP 404")
    if has(doc.title, NOT_FOUND_PHRASES) or (doc.small and doc.words < 60 and has(doc.text, NOT_FOUND_PHRASES)):
        return yes(0.8, "'not found' page")
    if doc.deep_link_to_front and doc.same_site:
        return yes(0.6, "deep URL redirected to the front page")
    if doc.deep_link_to_front and doc.deep_request and not doc.moved_to_own_domain:
        return yes(0.6, f"deep URL redirected to another site's front page ({doc.final.netloc})")
    return no(doc)


def client_error(doc: Document, found: dict) -> Flag:
    if 400 <= doc.status < 500 and doc.status not in (402, 404, 410, 429):
        return yes(1.0, f"HTTP {doc.status}")
    if doc.redirected and (FORBIDDEN_PATH.search(doc.final.path) or re.match(r"(403|access denied)\b", doc.title)):
        return yes(0.8, f"redirected to an access-denied page ({doc.final.path})")
    return Flag(False, 1.0, "rule")


def server_error(doc: Document, found: dict) -> Flag:
    if doc.status >= 500:
        return yes(1.0, f"HTTP {doc.status}")
    if doc.small and has(doc.text + " " + doc.title, MAINTENANCE_PHRASES):
        return yes(0.8, "maintenance or downtime notice")
    if doc.words < 100 and has(doc.text + " " + doc.title, REQUEST_FAILED_PHRASES):
        return yes(0.75, "the site says it couldn't process the request")
    return no(doc)


RULES: list[tuple[str, Callable[[Document, dict], Flag]]] = [
    ("payload_mismatch", payload_mismatch),
    ("rate_limited", rate_limited),
    ("bot_challenge", bot_challenge),
    ("geo_blocked", geo_blocked),
    ("unsupported_browser", unsupported_browser),
    ("interstitial", interstitial),
    ("auth", auth),
    ("paywall", paywall),
    ("parked", parked),
    ("gone", gone),
    ("not_found", not_found),
    ("client_error", client_error),
    ("server_error", server_error),
]


def evaluate(doc: Document, stop_confidence: float | None = None) -> tuple[dict[str, Flag], bool]:
    """Run the rules in priority order. With stop_confidence, stop at the first rejection that sure: every
    earlier column is already false, so it is the primary reason, and nothing later can change the outcome.
    Returns (flags evaluated, stopped early). A non-HTML payload stops the HTML rules (there is nothing to parse).
    """
    found: dict[str, Flag] = {}
    no_page = not doc.is_markup  # nothing to parse: only what the status code says
    for column, rule in RULES:
        found[column] = flag = (
            rule(doc, found) if column == "payload_mismatch" or not no_page else status_only(column, doc)
        )
        if stop_confidence is not None and flag.value and flag.confidence >= stop_confidence:
            return found, True
        if column == "payload_mismatch" and flag.value:
            no_page = True  # e.g. an empty 2xx HTML body
    return found, False


def status_only(column: str, doc: Document) -> Flag:
    """For bodies that aren't HTML: only what the status code says."""
    by_status = {
        "rate_limited": doc.status == 429,
        "geo_blocked": doc.status == 451,
        "paywall": doc.status == 402,
        "gone": doc.status == 410,
        "not_found": doc.status == 404,
        "client_error": 400 <= doc.status < 500 and doc.status not in (402, 404, 410, 429),
        "server_error": doc.status >= 500,
    }
    value = by_status.get(column, False)
    return Flag(value, 1.0, "rule", f"HTTP {doc.status}" if value else "")


def render_evidence(doc: Document) -> str | None:
    """Near-certain signs that the page's content is missing (an app shell): sent to the browser as missing content."""
    if doc.js_notice and doc.words < 50:
        return "noscript asks for JavaScript and almost no visible text"
    if doc.empty_mount and doc.words < 100:
        return "empty framework mount point and little visible text"
    if doc.template_placeholders >= 3 and doc.words < 1500:
        return f"{doc.template_placeholders} unrendered template placeholders"
    return None
