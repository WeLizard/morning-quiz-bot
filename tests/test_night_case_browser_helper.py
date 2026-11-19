"""Fixture clock and observable progress; no database, provider or second game engine."""
import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from tests.ui.night_case_browser import FixtureClock, wait_for_window, post_with_runtime_retry


class BrowserFixtureProgress(unittest.IsolatedAsyncioTestCase):
    def test_accelerated_clock_keeps_running_between_anchors_without_backward_time(self):
        ticks = [10.0]
        start = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
        clock = FixtureClock(start, monotonic=lambda: ticks[0])
        clock.advance_to(start + timedelta(days=1))
        outage_start = clock.now
        ticks[0] += .75
        self.assertGreater(clock.now, outage_start)
        self.assertEqual(clock.now - outage_start, timedelta(seconds=.75))
        clock.advance_to(start)
        self.assertGreaterEqual(clock.now, outage_start + timedelta(seconds=.75))

    async def test_zero_manual_worker_count_can_still_observe_background_winner(self):
        manual_count = 0
        views = iter([{'public': {'clock': {'window_seq': 7}}}, {'public': {'clock': {'window_seq': 8}}}])
        async def read(): return next(views)
        result = await wait_for_window(read, 7, timeout_seconds=.5, poll_seconds=0)
        self.assertEqual(manual_count, 0)
        self.assertEqual(result['public']['clock']['window_seq'], 8)

    async def test_no_progress_times_out_instead_of_repeated_clock_jumps(self):
        async def read(): return {'public': {'clock': {'window_seq': 7}}}
        with self.assertRaises(TimeoutError):
            await wait_for_window(read, 7, timeout_seconds=.01, poll_seconds=.001)

    async def test_transient_unavailable_read_is_bounded_and_excess_advances_fail(self):
        views = iter([None, {'public': {'clock': {'window_seq': 8}}}])
        async def read(): return next(views)
        self.assertEqual((await wait_for_window(read, 7, timeout_seconds=.5, poll_seconds=0))['public']['clock']['window_seq'], 8)
        async def skipped(): return {'public': {'clock': {'window_seq': 9}}}
        with self.assertRaises(AssertionError):
            await wait_for_window(skipped, 7, timeout_seconds=.5)

    async def test_runtime_retry_keeps_exact_bytes_and_only_accepts_original_command(self):
        class Response:
            def __init__(self, status, code): self.status, self.code = status, code
            async def json(self): return {'code': self.code}
        payload = b'{"command_id":"same-uuid","actor_seq":3,"window_seq":8,"params":{"text":"draft"}}'
        calls, observations = [], []
        replies = iter([Response(503, 'runtime_delayed'), Response(503, 'runtime_delayed'), Response(200, 'accepted')])
        async def send(data): calls.append(data); return next(replies)
        result = await post_with_runtime_retry(send, payload, poll_seconds=0, observations=observations)
        self.assertEqual(result.status, 200)
        self.assertEqual(calls, [payload, payload, payload])
        self.assertTrue(all(data is payload for data in calls))
        self.assertEqual([item['status'] for item in observations], [503, 503, 200])

    async def test_other_errors_are_not_retried(self):
        class Response:
            def __init__(self, status, code): self.status, self.code = status, code
            async def json(self): return {'code': self.code}
        for status, code in [(409, 'actor_stale'), (500, 'internal'), (503, 'game_quarantined'), (429, 'rate_limited')]:
            calls = []
            response = Response(status, code)
            async def send(data): calls.append(data); return response
            self.assertIs(await post_with_runtime_retry(send, b'original'), response)
            self.assertEqual(calls, [b'original'])

    async def test_runtime_retry_has_one_budget_including_a_stalled_send(self):
        async def stalled(data): await asyncio.sleep(1)
        with self.assertRaises(TimeoutError):
            await post_with_runtime_retry(stalled, b'original', timeout_seconds=.01)
        class Response:
            status = 503
            async def json(self): return {'code': 'runtime_delayed'}
        calls = []
        async def unavailable(data): calls.append(data); return Response()
        with self.assertRaises(TimeoutError):
            await post_with_runtime_retry(unavailable, b'original', timeout_seconds=.01, poll_seconds=.001)
        self.assertGreater(len(calls), 0)
        self.assertTrue(all(data == b'original' for data in calls))


if __name__ == '__main__':
    unittest.main()
