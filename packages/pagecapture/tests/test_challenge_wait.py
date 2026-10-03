import asyncio
from unittest.mock import Mock

from pagecapture.render import adaptive


def wait(monkeypatch, states, cap=1, progress_cap=3):
    clock = [0.0]
    monkeypatch.setattr(adaptive.time, "perf_counter", lambda: clock[0])

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(adaptive.asyncio, "sleep", sleep)

    class Page:
        async def evaluate(self, *args):
            return states[min(int(clock[0] * 2), len(states) - 1)]

    session = Mock()
    cleared = asyncio.run(adaptive.wait_out_challenge(Page(), session, cap, progress_cap))
    return cleared, clock[0], session


def test_progress_extends_wait_until_clearance(monkeypatch):
    states = [{"challenged": True, "ready": True, "progress": str(i)} for i in range(4)]
    states.append({"challenged": False, "ready": True})
    cleared, elapsed, _ = wait(monkeypatch, states)
    assert cleared and elapsed == 2


def test_stalled_challenge_does_not_extend_wait(monkeypatch):
    cleared, elapsed, _ = wait(monkeypatch, [{"challenged": True, "ready": True, "progress": "0"}])
    assert not cleared and elapsed == 1


def test_progress_cannot_exceed_hard_wait_cap(monkeypatch):
    states = [{"challenged": True, "ready": True, "progress": str(i)} for i in range(20)]
    cleared, elapsed, _ = wait(monkeypatch, states)
    assert not cleared and elapsed == 3


def test_terminal_denial_stops_immediately(monkeypatch):
    cleared, elapsed, session = wait(monkeypatch, [{"challenged": True, "ready": True, "denied": True}])
    assert not cleared and elapsed == 0
    session.log.assert_called_once_with("challenge denied")
