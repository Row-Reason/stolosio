"""Controlled origin for pacing experiments, served inside an isolated Docker network.

Three requests can execute concurrently; each successful request takes three seconds.
Further requests return 429 with Retry-After: 1. No external network requests occur.
"""

import asyncio
import json
from collections import Counter

active = 0
counts = Counter()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global active
    held = False
    try:
        await reader.readuntil(b"\r\n\r\n")
        if active >= 3:
            status, reason = 429, "Too Many Requests"
            extra = "Retry-After: 1\r\n"
            body = json.dumps({"error": "rate_limited"}).encode()
        else:
            active += 1
            held = True
            await asyncio.sleep(3)
            status, reason, extra = 200, "OK", ""
            body = json.dumps({"ok": True}).encode()
        counts[status] += 1
        writer.write(
            (
                f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n{extra}Connection: close\r\n\r\n"
            ).encode()
            + body
        )
        await writer.drain()
        print(json.dumps({"status": status, "active": active, "counts": dict(counts)}), flush=True)
    finally:
        if held:
            active -= 1
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", 80)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
