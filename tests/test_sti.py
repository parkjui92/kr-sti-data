import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KR_STI_DB", str(ROOT / "tests" / "_tmp.db"))
import sti  # noqa: E402


class TestEnvelope(unittest.TestCase):
    def test_ok(self):
        env = {"Sttsapitbldata": [{"head": [{"list_total_count": 1}, {"RESULT": {"CODE": "INFO-000"}}]},
                                   {"row": [{"WRTTIME_IDTFR_ID": 2024, "GRP_NM": "g", "CLS_NM": "c", "ITM_NM": "i", "DTA_VAL": 3, "UI_NM": "억원"}]}]}
        total, rows = sti.nabo_envelope(env)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["year"], "2024")
        self.assertEqual(rows[0]["val"], 3)

    def test_error_in_200(self):
        with self.assertRaises(RuntimeError):
            sti.nabo_envelope({"Sttsapitbldata": [{"head": [{"RESULT": {"CODE": "INFO-200", "MESSAGE": "no"}}]}]})
        with self.assertRaises(RuntimeError):
            sti.nabo_envelope({"RESULT": {"CODE": "ERROR-300", "MESSAGE": "key"}})


class TestCatalog(unittest.TestCase):
    def test_tables_have_name_and_verified(self):
        for src in ("kosis", "nabo"):
            for k, v in sti.CATALOG[src]["tables"].items():
                self.assertTrue(v.get("name"), k)
                self.assertRegex(v.get("verified_at", ""), r"^\d{4}-\d{2}-\d{2}$", k)

    def test_breaks_have_year_and_note(self):
        for b in sti.CATALOG["breaks"]:
            self.assertIsInstance(b["year"], int)
            self.assertTrue(b["note"])


class TestHelpers(unittest.TestCase):
    def test_year_chunks(self):
        self.assertEqual(list(sti._year_chunks(2011, 2024, 10)), [(2011, 2020), (2021, 2024)])
        self.assertEqual(list(sti._year_chunks(2024, 2024, 10)), [(2024, 2024)])

    def test_redact(self):
        self.assertNotIn("SECRET", sti._redact("https://kosis.kr/x?method=a&apiKey=SECRET"))
        self.assertNotIn("SECRET", sti._redact("https://nabo/x?STATBL_ID=T&KEY=SECRET"))

    def test_selftest(self):
        self.assertEqual(sti.selftest(), 0)


if __name__ == "__main__":
    unittest.main()
