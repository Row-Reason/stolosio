from datetime import UTC, datetime, timedelta

import pytest

from backend.proxy.adapters.browserless_cloud import BrowserlessCloudAdapter
from backend.proxy.adapters.cdp import DirectCdpAdapter, WebSocketProviderSession
from backend.proxy.adapters.registry import get_provider_adapter
from backend.proxy.contracts import (
    ProviderName,
)


class FakeWebSocket:
    def __init__(self, messages: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self.messages = messages or []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_direct_adapter_connects_to_assigned_browserless_worker(monkeypatch) -> None:
    request: dict[str, object] = {}

    async def fake_connect(url: str, **kwargs):
        request["url"] = url
        request["kwargs"] = kwargs
        return FakeWebSocket()

    monkeypatch.setattr("backend.proxy.adapters.cdp.connect", fake_connect)
    adapter = DirectCdpAdapter(
        ProviderName.BROWSERLESS,
        "ws://stolosio-browserless-2:3000",
    )

    session = await adapter.acquire(None, None)  # type: ignore[arg-type]

    assert session.provider is ProviderName.BROWSERLESS
    assert request == {
        "url": "ws://stolosio-browserless-2:3000",
        "kwargs": {"max_size": None, "proxy": None},
    }


@pytest.mark.asyncio
async def test_native_cdp_session_forwards_unknown_methods_without_interpreting_them() -> None:
    websocket = FakeWebSocket(
        ['{"id":7,"result":{"futureField":true},"sessionId":"page"}']
    )
    session = WebSocketProviderSession(
        ProviderName.BROWSERLESS,
        websocket,  # type: ignore[arg-type]
    )
    command = '{"id":7,"method":"Future.experimentalMethod","params":{"x":1}}'

    await session.send(command)
    messages = [message async for message in session.messages()]

    assert websocket.sent == [command]
    assert messages == ['{"id":7,"result":{"futureField":true},"sessionId":"page"}']


@pytest.mark.asyncio
async def test_native_session_close_does_not_manage_client_contexts() -> None:
    websocket = FakeWebSocket()
    session = WebSocketProviderSession(
        ProviderName.BROWSERLESS,
        websocket,  # type: ignore[arg-type]
    )

    await session.send('{"id":1,"method":"Target.createBrowserContext"}')
    await session.close()

    assert websocket.sent == ['{"id":1,"method":"Target.createBrowserContext"}']
    assert websocket.closed
    assert session.provider_ended_at is not None
    assert session.provider_started_at <= datetime.now(UTC)


def test_native_session_reports_provider_deadline_expiration() -> None:
    session = WebSocketProviderSession(
        ProviderName.BROWSERLESS,
        FakeWebSocket(),  # type: ignore[arg-type]
        timeout_started_at=datetime.now(UTC) - timedelta(seconds=10),
        session_timeout_seconds=5,
    )

    assert session.disconnect_reason == "provider_timeout"


def test_registry_has_only_the_browserless_adapters() -> None:
    browserless = get_provider_adapter(
        ProviderName.BROWSERLESS,
        endpoint="ws://browserless-worker:3000",
    )
    assert isinstance(browserless, DirectCdpAdapter)
    assert browserless.session_timeout_seconds == 600
    assert isinstance(
        get_provider_adapter(ProviderName.BROWSERLESS_CLOUD),
        BrowserlessCloudAdapter,
    )
