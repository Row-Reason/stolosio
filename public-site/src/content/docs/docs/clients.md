---
title: Connect your clients
description: Connect Playwright and CDP clients to the single Stolosio endpoint.
---

Stolosio exposes `WS /v1/connect` for browser automation. A client that already connects over CDP should only need an endpoint URL change. Playwright's `connect_over_cdp()` is the relevant transport; this is not the Playwright `browser_type.connect()` protocol.

## Complete Python example

From a checkout with `uv sync --locked` completed, save this as `first_session.py`:

```python
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(
            "ws://localhost:8411/v1/connect"
        )
        try:
            page = await browser.new_page()
            await page.goto("https://example.com")
            print(await page.content())
        finally:
            await browser.close()


asyncio.run(main())
```

Run it with `uv run python first_session.py`. This connects to a remote browser gateway; you do not need to launch a local Playwright browser.

## Select a provider

Sessions use the managed Browserless fleet (`browserless`) by default. To use paid Browserless cloud instead, name it in the Stolosio query namespace:

```text
ws://localhost:8411/v1/connect?stolosio.provider.slug=browserless_cloud
```

Browserless cloud also requires a configured token and operator-enabled provider capacity, and it is subject to admission limits. Stolosio never picks it on your behalf, and a session never moves to another provider.

## Fetch a page without automation

A client that only needs a page's content can call `POST /v1/capture` instead of driving a browser. Capture chooses between a plain HTTP fetch and a browser render by itself and returns the content or a failure that says why. See the [capture contract](https://github.com/elei-io/stolosio/blob/main/docs/CAPTURE.md).

## Close sessions

Close the browser connection in a `finally` block so exceptions in your client do not leave work running unnecessarily. Handle connection failures and protocol errors explicitly. Do not blindly retry operations with side effects.

## Compatibility boundary

CDP traffic passes through to the provider's browser, which remains authoritative for CDP behavior. See the [provider matrix](/docs/providers/) before choosing a provider.
