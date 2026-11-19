import unittest
from datetime import datetime, timezone

from domain.night_case_state import Clock, rules_snapshot
from domain.night_case_time import after_quiet, next_slot, resume_deadline


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TimeTests(unittest.TestCase):
    def setUp(self):
        self.rules = rules_snapshot("Europe/Berlin")

    def test_slot_strict_and_minimum_is_callers_responsibility(self):
        self.assertEqual(next_slot(utc("2026-01-01T07:30:00Z"), "Europe/Berlin", self.rules), utc("2026-01-01T08:00:00Z"))
        self.assertEqual(next_slot(utc("2026-01-01T08:00:00Z"), "Europe/Berlin", self.rules), utc("2026-01-01T18:00:00Z"))

    def test_quiet_boundary(self):
        self.assertEqual(after_quiet(utc("2026-01-01T22:00:00Z"), "Europe/Berlin", self.rules), utc("2026-01-02T07:00:00Z"))
        self.assertEqual(after_quiet(utc("2026-01-01T21:59:59Z"), "Europe/Berlin", self.rules), utc("2026-01-01T21:59:59Z"))

    def test_fold_uses_later_utc(self):
        d = self.rules.document()
        d["slots"] = ["02:30"]
        from domain.night_case_state import RulesSnapshot
        custom = RulesSnapshot.from_document(d, allow_custom=True)
        self.assertEqual(next_slot(utc("2026-10-25T00:00:00Z"), "Europe/Berlin", custom), utc("2026-10-25T01:30:00Z"))

    def test_gap_uses_next_valid_instant(self):
        d = self.rules.document()
        d["slots"] = ["02:30"]
        from domain.night_case_state import RulesSnapshot
        custom = RulesSnapshot.from_document(d, allow_custom=True)
        self.assertEqual(next_slot(utc("2026-03-28T23:00:00Z"), "Europe/Berlin", custom), utc("2026-03-29T01:00:00Z"))

    def test_resume_one_extension_only_when_deadline_in_outage(self):
        clock = Clock.from_document({"timezone":"Europe/Berlin","window_idx":1,"window_seq":1,"timer_seq":1,"opened_at":"2026-01-01T08:00:00Z","closes_at":"2026-01-01T18:00:00Z","early_not_before":"2026-01-01T08:30:00Z","slot_cursor":None,"phase":"investigation","opening_pending":False,"freeze_at":None,"forget_at":None,"resume_receipts":[]})
        outage = {"outage_id":"outage1","unavailable_from":"2025-12-31T12:00:00Z","resumed_at":"2026-01-01T18:00:00Z"}
        changed = resume_deadline(clock,outage,self.rules,utc("2026-01-01T18:00:00Z"))
        self.assertEqual(changed.closes_at,"2026-01-02T07:00:00Z")
        self.assertEqual(changed.timer_seq,2)
        self.assertEqual(resume_deadline(changed,outage,self.rules,utc("2026-01-01T18:00:00Z")).document(),changed.document())
        conflicting = {**outage, "unavailable_from": "2025-12-31T13:00:00Z"}
        with self.assertRaises(ValueError):
            resume_deadline(changed, conflicting, self.rules, utc("2026-01-01T18:00:00Z"))

    def test_resume_outside_deadline_does_not_rewind_clock(self):
        clock = Clock.from_document({"timezone":"Europe/Berlin","window_idx":1,"window_seq":1,"timer_seq":1,"opened_at":"2026-01-01T08:00:00Z","closes_at":"2026-01-01T18:00:00Z","early_not_before":"2026-01-01T08:30:00Z","slot_cursor":None,"phase":"investigation","opening_pending":False,"freeze_at":None,"forget_at":None,"resume_receipts":[]})
        outage = {"outage_id":"outage2","unavailable_from":"2026-01-01T09:00:00Z","resumed_at":"2026-01-01T10:00:00Z"}
        changed = resume_deadline(clock, outage, self.rules, utc("2026-01-01T10:00:00Z"))
        self.assertEqual(changed.closes_at, clock.closes_at)
        self.assertEqual(changed.timer_seq, clock.timer_seq)
        self.assertEqual(len(changed.resume_receipts), 1)

    def test_clock_rejects_short_open_window(self):
        document = {"timezone":"Europe/Berlin","window_idx":1,"window_seq":1,"timer_seq":1,"opened_at":"2026-01-01T08:00:00Z","closes_at":"2026-01-01T08:00:02Z","early_not_before":"2026-01-01T08:00:01Z","slot_cursor":None,"phase":"investigation","opening_pending":False,"freeze_at":None,"forget_at":None,"resume_receipts":[]}
        with self.assertRaises(ValueError):
            Clock.from_document(document)


if __name__ == "__main__":
    unittest.main()
