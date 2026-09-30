from dataclasses import asdict
from datetime import UTC, datetime

from pagecapture.cache import MethodEntry
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import CaptureMethodCacheEntry


class PostgresMethodCache:
    """pagecapture's MethodCache on PostgreSQL. Concurrent captures of one URL may each count a
    comparison or overwrite each other's; the entries are evidence counters, and a lost update only
    delays a decision."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> MethodEntry | None:
        async with self._sessions() as database:
            row = await database.get(CaptureMethodCacheEntry, key)
            return MethodEntry(**row.entry) if row is not None else None

    async def put(self, key: str, entry: MethodEntry) -> None:
        values = {
            "key": key,
            "entry": asdict(entry),
            "last_seen": datetime.fromtimestamp(entry.last_seen, UTC),
        }
        async with self._sessions.begin() as database:
            await database.execute(
                insert(CaptureMethodCacheEntry)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[CaptureMethodCacheEntry.key],
                    set_={"entry": values["entry"], "last_seen": values["last_seen"]},
                )
            )
