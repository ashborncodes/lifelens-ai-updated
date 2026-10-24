import sys, unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core

REF = date(2026, 10, 24)
SAMPLE = (Path(__file__).resolve().parents[1] / "samples" / "sample_notice.txt").read_text()


class Dates(unittest.TestCase):
    def test_full_text_date(self):
        h = core.find_dates("closes on 12 November 2026.", REF)[0]
        self.assertEqual(h["iso"], "2026-11-12"); self.assertEqual(h["flags"], [])

    def test_us_style(self):
        self.assertEqual(core.find_dates("Due March 5, 2027", REF)[0]["iso"], "2027-03-05")

    def test_missing_year_assumes_next_and_flags(self):
        h = core.find_dates("by 3 January", REF)[0]
        self.assertEqual(h["iso"], "2027-01-03"); self.assertTrue(h["flags"])

    def test_numeric_ambiguous_is_flagged(self):
        h = core.find_dates("by 05/06/2026", REF)[0]
        self.assertTrue(any("Ambiguous" in f for f in h["flags"]))

    def test_numeric_unambiguous_not_flagged(self):
        h = core.find_dates("by 25/12/2026", REF)[0]
        self.assertEqual(h["iso"], "2026-12-25"); self.assertEqual(h["flags"], [])

    def test_relative_is_flagged_not_resolved(self):
        h = core.find_dates("send it by next Friday", REF)[0]
        self.assertIsNone(h["iso"]); self.assertTrue(h["flags"])

    def test_invalid_date(self):
        self.assertIsNone(core.find_dates("by 31 November 2026", REF)[0]["iso"])

    def test_may_year_not_misread(self):
        self.assertEqual(core.find_dates("in May 2026", REF), [])


class Priority(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual([core.priority_for(x) for x in (None, -1, 2, 8, 30)],
                         ["Review", "Overdue", "High", "Medium", "Low"])


class Offline(unittest.TestCase):
    def setUp(self):
        self.r = core.analyze(SAMPLE, REF, use_llm=False)

    def test_deadline_linked_across_lines(self):
        t = next(t for t in self.r["tasks"] if "registration form" in t["task"])
        self.assertEqual(t["deadline_iso"], "2026-11-12")
        self.assertEqual(t["days_left"], 19)
        self.assertTrue(t["evidence_verified"])
        self.assertTrue(t["notes"])

    def test_event_date_is_a_key_date(self):
        self.assertTrue(any(k["iso"] == "2026-11-20" for k in self.r["key_dates"]))

    def test_all_evidence_verified(self):
        self.assertTrue(all(t["evidence_verified"] for t in self.r["tasks"]))


class Validation(unittest.TestCase):
    def test_invented_deadline_removed(self):
        raw = [{"task": "Submit form", "deadline_text": "30 December 2026",
                "evidence": "Students must submit the registration form before the deadline.", "notes": []}]
        t = core.validate(raw, SAMPLE, REF)[0]
        self.assertIsNone(t["deadline_iso"]); self.assertTrue(t["needs_review"])
        self.assertTrue(any("not in the source" in f for f in t["flags"]))

    def test_fake_evidence_flagged(self):
        raw = [{"task": "Pay fee", "deadline_text": "", "evidence": "Pay Rs 500 at the office.", "notes": []}]
        t = core.validate(raw, SAMPLE, REF)[0]
        self.assertFalse(t["evidence_verified"]); self.assertTrue(t["needs_review"])

    def test_llm_json_with_code_fence(self):
        s, tasks = core.parse_llm_json('```json\n{"summary":"x","tasks":[{"task":"A","deadline_text":"","evidence":"e"}]}\n```')
        self.assertEqual((s, tasks[0]["task"]), ("x", "A"))

    def test_good_llm_output_passes(self):
        raw = [{"task": "Bring ID card", "deadline_text": "20 November 2026",
                "evidence": "The event will take place on 20 November 2026.", "notes": []}]
        t = core.validate(raw, SAMPLE, REF)[0]
        self.assertEqual(t["deadline_iso"], "2026-11-20"); self.assertTrue(t["evidence_verified"])


class Fallback(unittest.TestCase):
    def test_llm_failure_falls_back(self):
        orig = core.llm_extract
        core.llm_extract = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            r = core.analyze(SAMPLE, REF, api_key="k", use_llm=True)
        finally:
            core.llm_extract = orig
        self.assertEqual(r["mode"], "Offline heuristic"); self.assertIn("failed", r["warning"]); self.assertTrue(r["tasks"])


class Exports(unittest.TestCase):
    def test_ics_and_md(self):
        r = core.analyze(SAMPLE, REF, use_llm=False)
        self.assertIn("DTSTART;VALUE=DATE:20261112", core.to_ics(r))
        self.assertIn("Source:", core.to_markdown(r))


if __name__ == "__main__":
    unittest.main()
