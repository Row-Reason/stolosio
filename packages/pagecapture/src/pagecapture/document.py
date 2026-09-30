"""A parsed HTTP response. Everything rules and features need is computed lazily and at most once.

Cheap facts (status, headers, redirects, content type) need no parsing, so early exits in the classifier
never pay for the HTML parse. The first access to anything textual parses the page once (lxml) and walks it
once to count words per element, region and visibility.
"""

import re
import warnings
from dataclasses import dataclass
from functools import cached_property
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

MARKUP_TYPES = {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}
INVISIBLE = {"script", "style", "noscript", "template", "svg", "title", "head", "meta", "link"}
CHROME = {"nav", "header", "footer", "aside"}
MOUNT_IDS = {"root", "app", "__next", "__nuxt", "___gatsby", "svelte", "main-app", "application", "react-root"}
FRONT_PATH = re.compile(r"^/?([a-z]{2}([-_][a-z]{2})?)?/?$", re.I)  # "/", "/fr", "/en-us"
LOGIN_PATH = re.compile(
    r"/(login|log-in|signin|sign-in|sign_in|signup|sign-up|auth|enter|account/login|users/sign_in)\b", re.I
)
SEARCH_PATH = re.compile(r"/(search|suche|recherche|buscar)(/|\.\w+$|$)", re.I)
HYDRATION = re.compile(r"__NEXT_DATA__|__NUXT__|__INITIAL_STATE__|__APOLLO_STATE__|__PRELOADED_STATE__|self\.__next_f")
JS_REDIRECT = re.compile(r"location(\.href)?\s*=|location\.(replace|assign)\(", re.I)
LANDER_REDIRECT = re.compile(r"""location(\.href)?\s*=\s*["'][^"']*/lander""", re.I)
# Chinese, Japanese, Thai, Lao, Khmer and Burmese are written without spaces between words.
NO_SPACE_SCRIPT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff]")


def word_count(text: str) -> int:
    """Words in spaced scripts plus one word per two characters in scripts without spaces."""
    no_space = len(NO_SPACE_SCRIPT.findall(text))
    return len(NO_SPACE_SCRIPT.sub(" ", text).split()) + no_space // 2


def class_words(el: Tag) -> frozenset[str]:
    """Words of an element's class and id, split on spaces, underscores and dashes."""
    raw = " ".join(el.get("class") or []) + " " + (el.get("id") or "")
    return frozenset(re.split(r"[\s_]+|-(?=[a-z])", raw.lower())) - {""}


def is_hidden(el: Tag) -> bool:
    style = (el.get("style") or "").replace(" ", "").lower()
    return (
        el.get("hidden") is not None
        or el.get("aria-hidden") == "true"
        or "display:none" in style
        or "visibility:hidden" in style
    )


@dataclass
class TextStats:
    text: str  # visible text, lower-cased, whitespace collapsed
    words: int  # all visible words (hidden streamed segments included: their text is in the HTML)
    main_words: int | None  # inside <main>/role=main, None without one
    content_words: int  # outside nav/header/footer/aside
    link_words: int
    hidden_words: int  # inside hidden elements (streamed server rendering puts real content there)
    body_words: int  # <article>/<main>, else <p> text; the whole page when those hold under 5%
    per_element: dict[int, int]  # id(element) -> visible words inside it
    glued: str = ""  # the same text with nothing between elements (as browsers join inline elements)


class Document:
    def __init__(self, url: str, resp: requests.Response):
        self.url = url
        self.resp = resp
        self.status = resp.status_code
        self.requested = urlparse(url)
        self.final = urlparse(resp.url)
        self.headers = {k.lower(): v.lower() for k, v in resp.headers.items()}
        self.content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()

    # ---- cheap facts: no parsing ----------------------------------------------------------------------------

    @property
    def is_markup(self) -> bool:
        return not self.content_type or self.content_type in MARKUP_TYPES or self.content_type.endswith("+xml")

    @property
    def empty_body(self) -> bool:
        return not self.resp.content.strip()

    @property
    def redirected(self) -> bool:
        return bool(self.resp.history)

    @property
    def same_site(self) -> bool:
        def host(u) -> str:
            return u.netloc.lower().split(":")[0].removeprefix("www.")

        return host(self.final) == host(self.requested)

    @property
    def deep_link_to_front(self) -> bool:
        requested_front = FRONT_PATH.match(self.requested.path) and not self.requested.query
        return self.redirected and bool(FRONT_PATH.match(self.final.path)) and not requested_front

    @property
    def deep_request(self) -> bool:
        """The requested URL points into a site (two or more path segments, or a query), not at a section front."""
        return len([s for s in self.requested.path.split("/") if s]) >= 2 or bool(self.requested.query)

    @property
    def moved_to_own_domain(self) -> bool:
        """Redirected to a domain named after the requested path (mozilla.org/firefox/ -> firefox.com): the thing
        moved to its own site, it isn't lost."""
        labels = [
            x for x in self.final.netloc.lower().split(":")[0].split(".") if x not in ("www", "com", "org", "net")
        ]
        path = (self.requested.path + "?" + self.requested.query).lower()
        return any(len(x) >= 4 and x in path for x in labels)

    @property
    def redirected_to_login(self) -> bool:
        return (
            self.redirected
            and bool(LOGIN_PATH.search(self.final.path + "?" + self.final.query))
            and not LOGIN_PATH.search(self.requested.path)
        )

    @property
    def search_without_query(self) -> bool:
        return bool(SEARCH_PATH.search(self.final.path)) and not self.requested.query and not self.final.query

    # ---- parsed facts --------------------------------------------------------------------------------------

    @cached_property
    def html(self) -> str:
        """Decoded body; without a charset header, trust the page's <meta charset> over requests' Latin-1 default."""
        resp = self.resp
        if "charset=" in resp.headers.get("Content-Type", "").lower():
            return resp.text
        m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", resp.content[:4096], re.I)
        encoding = m.group(1).decode() if m else resp.apparent_encoding
        try:
            return resp.content.decode(encoding or "utf-8", errors="replace")
        except LookupError:
            return resp.content.decode("utf-8", errors="replace")

    @cached_property
    def markup(self) -> str:
        return self.html.lower()

    @cached_property
    def soup(self) -> BeautifulSoup:
        with warnings.catch_warnings():  # XML (feeds, sitemaps) is read for its text like HTML, on purpose
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            return BeautifulSoup(self.html, "lxml")

    @cached_property
    def title(self) -> str:
        return self.soup.title.get_text(" ", strip=True).lower() if self.soup.title else ""

    @cached_property
    def stats(self) -> TextStats:
        """One depth-first pass over the page: every node is visited once, whatever the nesting depth. Region flags
        (invisible, chrome, link, hidden, main) are inherited down the walk; word counts are summed up it."""
        per_element: dict[int, int] = {}
        parts: list[str] = []
        totals = {"words": 0, "main": 0, "chrome": 0, "link": 0, "hidden": 0}
        main = self.main
        root = self.soup
        # stack entries: (element, flags, children iterator); counts[i] = words inside stack[i] so far
        stack = [(root, (False, False, False, False), iter(root.children))]
        counts = [0]
        while stack:
            node, flags, children = stack[-1]
            child = next(children, None)
            if child is None:
                stack.pop()
                words = counts.pop()
                per_element[id(node)] = words
                if counts:
                    counts[-1] += words
                continue
            chrome, link, hidden, in_main = flags
            if isinstance(child, Tag):
                if child.name in INVISIBLE and not (child.name == "template" and child.has_attr("shadowrootmode")):
                    continue  # (a declarative shadow root is rendered content: web components, as we serialise them)
                stack.append(
                    (
                        child,
                        (
                            chrome or child.name in CHROME,
                            link or child.name == "a",
                            hidden or is_hidden(child),
                            in_main or child is main,
                        ),
                        iter(child.children),
                    )
                )
                counts.append(0)
            elif isinstance(child, NavigableString) and type(child).__name__ not in (
                "Comment",
                "Doctype",
                "CData",
                "ProcessingInstruction",
                "Declaration",
            ):
                text = child.strip()
                if not text:
                    continue
                wc = word_count(text)
                parts.append(text)
                counts[-1] += wc
                totals["words"] += wc
                totals["main"] += wc if in_main else 0
                totals["chrome"] += wc if chrome else 0
                totals["link"] += wc if link else 0
                totals["hidden"] += wc if hidden else 0
        words = totals["words"]
        article = self.soup.find("article") or main
        body_words = (
            per_element.get(id(article), 0)
            if article is not None
            else sum(per_element.get(id(p), 0) for p in self.soup.find_all("p"))
        )
        if body_words < 0.05 * words:
            body_words = words
        return TextStats(
            text=re.sub(r"\s+", " ", " ".join(parts)).lower(),
            words=words,
            main_words=totals["main"] if main is not None else None,
            content_words=words - totals["chrome"],
            link_words=totals["link"],
            hidden_words=totals["hidden"],
            body_words=body_words,
            per_element=per_element,
            glued=re.sub(r"\s+", " ", "".join(parts)).lower(),
        )

    @cached_property
    def main(self) -> Tag | None:
        return self.soup.find("main") or self.soup.find(attrs={"role": "main"})

    @property
    def text(self) -> str:
        return self.stats.text

    @property
    def words(self) -> int:
        return self.stats.words

    @property
    def small(self) -> bool:
        """Phrase rules only apply to small pages, so a banner on a real page doesn't trigger them."""
        return self.words < 300

    @cached_property
    def scripts(self) -> list[Tag]:
        return self.soup.find_all("script")

    @cached_property
    def external_scripts(self) -> int:
        return sum(bool(s.get("src")) or s.get("type") == "module" for s in self.scripts)

    @cached_property
    def hydration_chars(self) -> int:
        return sum(
            len(s.string or "")
            for s in self.scripts
            if s.get("type") == "application/json" or HYDRATION.search((s.get("id") or "") + (s.string or "")[:300])
        )

    @cached_property
    def noscript_text(self) -> str:
        return " ".join(n.get_text(" ", strip=True) for n in self.soup.find_all("noscript")).lower()

    @cached_property
    def js_notice(self) -> bool:
        return "javascript" in self.noscript_text or "enable js" in self.noscript_text

    @cached_property
    def empty_mount(self) -> bool:
        return any(
            el["id"].lower() in MOUNT_IDS and not el.get_text(strip=True) and not el.find(True)
            for el in self.soup.find_all(id=True)
        )

    @cached_property
    def template_placeholders(self) -> int:
        """Unrendered Angular/Vue/Handlebars placeholders in visible text (code samples excluded)."""
        code = " ".join(c.get_text(" ", strip=True) for c in self.soup.find_all(["pre", "code"]))
        return self.text.count("{{") - code.count("{{")

    @cached_property
    def meta_refresh(self) -> bool:
        return bool(self.soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)}))

    @cached_property
    def js_redirect(self) -> bool:
        return len(self.html) < 5000 and bool(JS_REDIRECT.search(self.html))

    @cached_property
    def lander_redirect(self) -> bool:
        return bool(LANDER_REDIRECT.search(self.html[:5000]))

    @cached_property
    def password_inputs(self) -> int:
        return len(self.soup.select("input[type=password]"))

    @cached_property
    def search_inputs(self) -> int:
        return len(
            self.soup.select(
                "input[type=search], input[name=q], input[name=query], input[name=s], "
                "input[name=search], input[name=keyword], input[name=keywords]"
            )
        )

    @cached_property
    def streamed_segments(self) -> int:
        return len(self.soup.find_all("div", attrs={"hidden": True, "id": re.compile(r"^S:\d+")}))

    @cached_property
    def heading_ancestors(self) -> set[int]:
        """Elements that contain a heading (for "does this block have a title?")."""
        found = set()
        for h in self.soup.find_all(["h1", "h2", "h3", "h4"]):
            found.update(id(p) for p in h.parents if isinstance(p, Tag))
            found.add(id(h))
        return found

    @cached_property
    def media_ancestors(self) -> set[int]:
        """Elements that contain media or controls (an element with those isn't an empty spot)."""
        found = set()
        for m in self.soup.find_all(["img", "picture", "video", "iframe", "a", "input", "button", "svg"]):
            found.update(id(p) for p in m.parents if isinstance(p, Tag))
            found.add(id(m))
        return found
