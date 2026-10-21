import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sti


class TestFetchSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = patch.object(sti, "DB_PATH", Path(self.tmp.name) / "cache.db")
        self.db.start(); self.addCleanup(self.db.stop)

    def test_invalid_chunk_and_range(self):
        for values in ((2010, 2020, 0), (2010, 2020, -1), (2025, 2020, 1)):
            with self.assertRaises(ValueError): list(sti._year_chunks(*values))

    def fetch(self, cells, start=2024, levels=None):
        args = SimpleNamespace(org="127", tbl="T", all=False, frm=start, to=2024, chunk=10, verbose=False)
        meta = (levels or {"1": ("분류", [("a", "A")])}, [("i", "금액")], ("table", "년", "2024", "2024"))
        with patch.object(sti, "_kosis_meta", return_value=meta), patch.object(sti, "kosis_call", return_value=cells), contextlib.redirect_stdout(io.StringIO()):
            sti.kosis_fetch(args)

    def cell(self, key, value="1"):
        return {"PRD_DE": "2024", "ITM_ID": "i", "C1": key, "DT": value}

    def test_refresh_removes_disappeared_cells(self):
        self.fetch([self.cell("a"), self.cell("b")])
        self.fetch([self.cell("a", "2")])
        con = sti.open_db(); self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT c1,dt FROM kosis_cells").fetchall(), [("a", "2")])

    def test_missing_value_preserves_previous_chunk(self):
        self.fetch([self.cell("a")])
        with self.assertRaises(RuntimeError): self.fetch([self.cell("b", None)])
        con = sti.open_db(); self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT c1 FROM kosis_cells").fetchall(), [("a",)])

    def test_unsupported_levels_and_empty_overlap(self):
        with self.assertRaises(SystemExit): self.fetch([], start=2025)
        with self.assertRaises(SystemExit): self.fetch([], levels={"5": ("L5", [("a", "A")])})

    def test_nabo_refresh_replaces_and_failure_preserves(self):
        def row(year):
            return dict(year=year, grp="g", cls="c", itm="i", val="1", unit="억원")
        args = SimpleNamespace(tbl="T", all=False)
        def fetch(total, rows):
            with patch.object(sti, "get_key", return_value="fake"), patch.object(sti, "http_json", return_value={}), patch.object(sti, "nabo_envelope", return_value=(total, rows)), contextlib.redirect_stdout(io.StringIO()):
                sti.nabo_fetch(args)
        fetch(2, [row("2023"), row("2024")])
        fetch(1, [row("2024")])
        with self.assertRaises(RuntimeError): fetch(1, [])
        with self.assertRaises(RuntimeError): fetch(2, [row("2024"), row("2024")])
        con = sti.open_db(); self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT year FROM nabo_rows").fetchall(), [("2024",)])
