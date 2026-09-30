# How large-scale crawlers approach rendering

Notes from research on 2026-09-29, and what we took from each.

| Who | Approach | Lesson |
|---|---|---|
| Google | Crawl raw HTML first, queue pages for an evergreen-Chromium renderer (WRS). Rendering stops when the event loop is idle, timers are sped up, no interaction: it never scrolls or clicks, but uses a ~10,000 px tall viewport so viewport-triggered lazy loading fires. | Idle detection + tall viewport, no interaction. Our probes: tall viewport alone misses scroll-driven lists. |
| Bing | Evergreen Edge renderer; says rendering JS at scale on every page is hard, asks sites to serve pre-rendered HTML to bots. | Rendering everything is too expensive even for a search engine. |
| Common Crawl, AI crawlers | Raw HTML only (Nutch). GPTBot/ClaudeBot fetch JS files but don't execute them (Vercel/MERJ, 500M+ fetches). | Plain HTTP is the cheap norm, and misses client-rendered content. |
| Web archives (Umbra, Brozzler, Browsertrix) | Real browser per page, load + network idle, then behaviours: auto-scroll while new elements appear, site-specific scripts. Up to 90 s per page. | The fidelity end: thorough, slow, expensive. |
| Brunelle et al., ODU 2015 | Classifier on 12 DOM features (79% accurate) picks Heritrix or a headless browser per page; browser 12× slower but finds 1.75× more URLs; hybrid 5.2× faster than browser-only. | A two-tier "fast unless needed" design pays off; raw-HTML classification is only moderately accurate. |
| Crawlee adaptive crawler | Runs HTTP and browser on a sample, compares results, learns per site which suffices, keeps re-checking. | Learn from side-by-side runs, keep verifying (our canary idea). |
| Zyte API | Picks the leanest technology per website automatically and adapts over time. | Per-site automatic tuning works commercially. |

Sources:
[Google lazy-loading guidance](https://developers.google.com/search/docs/crawling-indexing/javascript/lazy-loading),
[Google 5-second render myth](https://tamethebots.com/blog-n-bits/the-5-second-google-render-limit-myth),
[Bing dynamic rendering](https://blogs.bing.com/webmaster/october-2018/bingbot-Series-JavaScript,-Dynamic-Rendering,-and-Cloaking-Oh-My),
[Evergreen Bingbot](https://blogs.bing.com/webmaster/october-2019/the-new-evergreen-bingbot-simplifying-seo-by-leveraging-microsoft-edge),
[Vercel: the rise of the AI crawler](https://vercel.com/blog/the-rise-of-the-ai-crawler),
[Brozzler (Archive-It)](https://archive-it.org/blog/the-stack-brozzler/),
[Browsertrix behaviors](https://crawler.docs.browsertrix.com/user-guide/behaviors/),
[Brunelle et al., two-tiered crawling](https://ar5iv.arxiv.org/html/1508.02315),
[Crawlee adaptive crawler](https://crawlee.dev/python/docs/guides/adaptive-playwright-crawler),
[Zyte API FAQ](https://docs.zyte.com/zyte-api/faq.html).
