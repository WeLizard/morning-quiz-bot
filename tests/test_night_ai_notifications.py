"""AI admin/system pointers never enter generic delivery claims."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects.postgresql import dialect

from storage.notifications import NotificationQueue


def test_generic_claim_filters_control_namespaces_before_lock_even_with_explicit_kinds():
    seen = []
    class Session:
        async def scalar(self, query):
            seen.append(str(query.compile(dialect=dialect(), compile_kwargs={'literal_binds': True})))
            return None
    @asynccontextmanager
    async def transaction():
        yield Session()
    async def run():
        queue = NotificationQueue(SimpleNamespace(transaction=transaction))
        assert await queue.claim('test', kinds={'night_ai_cleanup', 'mafia.phase'},
                                 now=datetime.now(timezone.utc)) is None
    asyncio.run(run())
    sql, = seen
    before_locks = sql.split('FOR UPDATE')[0]
    assert "night/_ai/_" in before_locks
    assert "'admin:'" in before_locks and "'system:'" in before_locks
    assert before_locks.count('NOT LIKE') == 3
    assert 'SKIP LOCKED' in sql
