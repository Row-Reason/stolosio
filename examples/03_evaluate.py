"""Evaluate JavaScript through Stolosio's CDP endpoint."""

import asyncio
import os

from playwright.async_api import async_playwright

STOLOSIO_CDP_URL = os.getenv(
    "STOLOSIO_CDP_URL",
    "ws://localhost:8411/v1/connect",
)


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(STOLOSIO_CDP_URL)
        page = await browser.new_page()

        await page.goto("https://example.com")
        title = await page.evaluate("document.title")

        assert title == "Example Domain"

        print("JavaScript evaluation succeeded")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
