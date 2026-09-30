"""JavaScript run inside the page by the adaptive renderer."""

# Visible text and detail-looking links (a rough "items in lists" count). Text inside containers of known ad and
# native-ad networks is reported separately: it isn't page content, and it mustn't count as something plain HTTP
# was missing. Vendor names only: generic words ("sponsored", "promoted") would also match real sections, and a
# real section wrongly set aside could teach the method cache to skip rendering where it's needed. Unknown networks
# are the safe failure: their ads just look like content, which costs a render.
AD_VENDORS = (
    "taboola",
    "outbrain",
    "popin",
    "logly",
    "uzou",
    "fluct",
    "microad",
    "i-mobile",
    "imobile",
    "gmossp",
    "yads",
    "adsbygoogle",
    "google_ads_iframe",
    "div-gpt-ad",
    "criteo",
    "teads",
    "mgid",
    "revcontent",
)
AD_SELECTOR = ",".join(f'[id*="{w}" i],[class*="{w}" i]' for w in AD_VENDORS) + ",ins.adsbygoogle"
# Installed before any of the page's own scripts: counts DOM changes, so the renderer can tell a still page from a
# busy one without shipping the page's text back and forth.
MUTATION_COUNTER = """(() => {
  window.__pcMut = 0;
  new MutationObserver(() => { window.__pcMut++; })
    .observe(document, {subtree: true, childList: true, characterData: true});
})();"""

MUTATIONS = "() => window.__pcMut || 0"

# Open shadow roots (web components): innerText and outerHTML don't reach into them, so pages built from components
# look empty without this. SHADOW_TEXT is a function body, inlined where text is collected.
SHADOW_TEXT = """
  const shadowText = () => {
    const out = [];
    const walk = (root) => {
      for (const el of root.querySelectorAll('*')) {
        if (!el.shadowRoot) continue;
        for (const child of el.shadowRoot.children) {
          if (!['STYLE', 'SCRIPT', 'TEMPLATE', 'SLOT'].includes(child.tagName)) out.push(child.innerText || '');
        }
        walk(el.shadowRoot);
      }
    };
    walk(document);
    return out.join('\\n');
  };"""

BODY_TEXT = (
    "() => {"
    + SHADOW_TEXT
    + """
  const text = document.body ? document.body.innerText : '';
  const shadow = shadowText();
  return shadow ? text + '\\n' + shadow : text;
}"""
)

# Lines of visible text and detail-looking links not reported before (the page remembers what it has sent), minus
# text inside known ad containers.
SNAPSHOT = (
    """() => {"""
    + SHADOW_TEXT
    + """
  const seen = window.__pcSeen || (window.__pcSeen = new Set());
  const seenItems = window.__pcItems || (window.__pcItems = new Set());
  const ads = new Set();
  for (const el of document.querySelectorAll(AD_SELECTOR)) {
    if (el.parentElement && el.parentElement.closest(AD_SELECTOR)) continue;
    for (const l of (el.innerText || '').split('\\n')) { const t = l.trim(); if (t) ads.add(t); }
  }
  const lines = [];
  for (const l of ((document.body ? document.body.innerText : '') + '\\n' + shadowText()).split('\\n')) {
    const t = l.trim();
    if (t && !ads.has(t) && !seen.has(t)) { seen.add(t); lines.push(t); }
  }
  const items = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href') || '';
    if (/\\/(item|items|product|products|p|listing|ad|dp|article|story|news|watch)\\/|\\/\\d{5,}/i.test(h) && !seenItems.has(a.href)) {
      seenItems.add(a.href); items.push(a.href);
    }
  }
  return {lines, items, mut: window.__pcMut || 0};
}""".replace("AD_SELECTOR", "`" + AD_SELECTOR + "`")
)

# Is the page still starting (little text, empty app container) or showing loading placeholders?
PAGE_STATE = (
    """() => {"""
    + SHADOW_TEXT
    + """
  const text = (document.body ? document.body.innerText : '') + shadowText();
  const mount = [...document.querySelectorAll('#root,#app,#__next,#__nuxt,#___gatsby,[data-reactroot]')]
    .some(e => !(e.innerText || e.textContent || '').trim());
  let pending = 0;
  for (const el of document.querySelectorAll('[aria-busy="true"],[class*="skeleton" i],[class*="shimmer" i],[class*="loading" i],[class*="spinner" i]')) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width > 20 && r.height > 20 && cs.display !== 'none' && cs.visibility !== 'hidden'
        && !(el.innerText || el.textContent || '').trim()) pending++;
  }
  // bytes transferred as the page itself saw them (cross-origin resources without Timing-Allow-Origin report 0)
  const nav = performance.getEntriesByType('navigation')[0];
  const bytes = performance.getEntriesByType('resource').reduce((a, e) => a + (e.transferSize || 0), nav ? nav.transferSize : 0);
  return {chars: text.length, mount, pending, bytes};
}"""
)

# Click a reject / necessary-only button in an obvious consent dialog. Never "accept all": the
# privacy-preserving choice, and it doesn't consent on the site owner's terms for anyone.
REJECT_CONSENT = """() => {
  const words = /^(reject all|reject|decline|decline all|deny|refuse|only necessary|necessary only|use necessary cookies only|continue without accepting|alle ablehnen|ablehnen|tout refuser|refuser|rechazar todo|rechazar|rifiuta tutto|rifiuta|weiger|avvisa alla|hylkää kaikki|hylkää|拒否|拒否する|すべて拒否)$/i;
  for (const b of document.querySelectorAll('button, [role=button]')) {
    const t = (b.innerText || '').trim();
    if (t.length < 40 && words.test(t) && b.offsetParent !== null) { b.click(); return t; }
  }
  return null;
}"""

# Scroll the window by `factor` screens, or, when the window doesn't scroll, the largest inner panel that
# does (apps that scroll inside a container). factor 0 only reports the state.
SCROLL_STEP = """(factor) => {
  const doc = document.scrollingElement || document.documentElement;
  let t = window.__pcTarget;
  if (!t || !t.isConnected) {
    t = null;
    if (doc.scrollHeight > window.innerHeight * 1.2) t = doc;
    else {
      let best = 0;
      for (const el of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(el);
        if (!/(auto|scroll)/.test(cs.overflowY) || el.scrollHeight < el.clientHeight + 200) continue;
        const area = el.clientWidth * el.clientHeight;
        if (area > best && area > 0.3 * window.innerWidth * window.innerHeight) { best = area; t = el; }
      }
    }
    window.__pcTarget = t;
  }
  if (!t) return {scrollable: false, inner: false, at_bottom: true};
  const view = t === doc ? window.innerHeight : t.clientHeight;
  if (factor > 0) { if (t === doc) window.scrollBy(0, view * factor); else t.scrollBy(0, view * factor); }
  return {scrollable: true, inner: t !== doc, at_bottom: t.scrollTop + view >= t.scrollHeight - 5};
}"""


# Is the page a bot challenge right now? (arg: [titles, markup markers], from classify.rules)
CHALLENGE_STATE = """([titles, markers]) => {
  const title = (document.title || '').toLowerCase();
  const html = document.documentElement ? document.documentElement.innerHTML.slice(0, 200000).toLowerCase() : '';
  return {challenged: titles.some(t => title.includes(t)) || markers.some(m => html.includes(m)),
          ready: document.readyState !== 'loading'};
}"""

# The whole document as HTML, with its doctype (what page.content() returns)
OUTER_HTML = """() => {
  const d = document.doctype;
  const doctype = d ? `<!DOCTYPE ${d.name}${d.publicId ? ` PUBLIC "${d.publicId}"` : ''}${d.systemId ? ` "${d.systemId}"` : ''}>` : '';
  const html = document.documentElement;
  if (!html) return '';
  // open shadow roots are serialised as declarative shadow DOM (<template shadowrootmode="open">), which browsers
  // and HTML parsers read back; pages without any keep plain outerHTML
  const roots = [];
  const walk = (root) => { for (const el of root.querySelectorAll('*')) if (el.shadowRoot) { roots.push(el.shadowRoot); walk(el.shadowRoot); } };
  walk(document);
  if (!roots.length || typeof html.getHTML !== 'function') return doctype + html.outerHTML;
  const attrs = [...html.attributes].map(a => ` ${a.name}="${a.value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"`).join('');
  return `${doctype}<html${attrs}>${html.getHTML({serializableShadowRoots: true, shadowRoots: roots})}</html>`;
}"""

# Large results travel gzipped and in chunks. Over a long, slow link to a remote browser (Browserless from Japan:
# ~0.5 s per call, ~25 KB/s) a big CDP message takes long enough to time out, and a timed-out message still streams
# on and blocks every call behind it. The page keeps the result (as JSON, gzipped and base64 when large) and hands out
# slices; the first slice comes back with the call itself.
CHUNK = 48_000


def chunked(fn: str) -> str:
    """Wrap a function expression (no in-page eval, which a page's CSP may forbid) so its result is kept as JSON."""
    return f"""async ([arg, size, id]) => {{
  let out = JSON.stringify(await ({fn})(arg));
  if (out === undefined) return {{none: true, head: '', more: false, gz: false}};
  let gz = false;
  if (out.length > size && typeof CompressionStream !== 'undefined') {{
    const buf = await new Response(new Blob([out]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer();
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    out = btoa(bin);
    gz = true;
  }}
  // kept per call, so a late (timed-out) call can't clobber it; lengths are UTF-16 units, so the page says when it's done
  if (out.length > size) (window.__pcOuts = window.__pcOuts || {{}})[id] = out;
  return {{none: false, head: out.slice(0, size), more: out.length > size, gz}};
}}"""


SLICE = """([id, start, size]) => {
  const out = (window.__pcOuts || {})[id];
  if (out === undefined) return null;
  const more = start + size < out.length;
  if (!more) delete window.__pcOuts[id];
  return {part: out.slice(start, start + size), more};
}"""
