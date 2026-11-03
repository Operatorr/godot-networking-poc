#!/usr/bin/env python3
"""Window selection and counter splitting are what the climb's numbers rest on."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze as an


def ticks(populations, start=1):
    return [{"tick": start + i, "authenticated": p} for i, p in enumerate(populations)]


class SelectWindow(unittest.TestCase):
    def test_takes_first_consecutive_ticks_at_full_population(self):
        rows = ticks([1] * 5 + [10] * 7)
        window, longest = an.select_window(rows, 10, want=4)
        self.assertEqual([r["tick"] for r in window], [6, 7, 8, 9])
        self.assertEqual(longest, 7)

    def test_a_population_dip_restarts_the_window(self):
        rows = ticks([10] * 3 + [9] + [10] * 4)
        window, longest = an.select_window(rows, 10, want=4)
        self.assertEqual([r["tick"] for r in window], [5, 6, 7, 8])
        self.assertEqual(longest, 4)

    def test_a_tick_gap_breaks_the_run(self):
        rows = ticks([10] * 3) + ticks([10] * 3, start=9)
        window, longest = an.select_window(rows, 10, want=4)
        self.assertEqual(len(window), 3)
        self.assertEqual(longest, 3)

    def test_short_run_is_reported_but_not_full_length(self):
        window, longest = an.select_window(ticks([10] * 3 + [8] * 2), 10, want=1800)
        self.assertEqual(len(window), 3)
        self.assertEqual(longest, 3)

    def test_never_full_gives_no_window(self):
        self.assertEqual(an.select_window(ticks([8] * 3), 10), ([], 0))


class SplitCounter(unittest.TestCase):
    def test_phases_sum_to_whole_run(self):
        rows = [{"ts": t, "udp": {"snmp": {"RcvbufErrors": v}}} for t, v in
                [(0, 100), (10, 104), (20, 110), (30, 125), (40, 130)]]
        self.assertEqual(an.split_counter(rows, "RcvbufErrors", 10, 30),
                         {"whole": 30, "ramp": 4, "minute": 21, "tail": 5})

    def test_no_window_keeps_the_whole_run_delta(self):
        rows = [{"ts": t, "udp": {"snmp": {"RcvbufErrors": v}}} for t, v in [(0, 100), (10, 117)]]
        self.assertEqual(an.split_counter(rows, "RcvbufErrors"),
                         {"whole": 17, "ramp": None, "minute": None, "tail": None})


class NeverFullRun(unittest.TestCase):
    """224 of 225 bots on every Tick: no window, but the socket evidence must survive."""

    def analyze(self, rcvbuf):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            (trial / "server").mkdir()
            columns = ["utc_ns", "mono_ns", "work_ns", "budget_pct", *an.INT_COLS]
            lines = [",".join(columns)]
            for tick in range(1, 4):
                row = {c: 0 for c in columns} | {"tick": tick, "authenticated": 224}
                lines.append(",".join(str(row[c]) for c in columns))
            (trial / "server/ticks.csv").write_text("\n".join(lines) + "\n")
            samples = [{"ts": t, "udp": {"snmp": {"RcvbufErrors": v, "SndbufErrors": 5},
                                         "socket": {"drops": v, "rx_queue": 9, "tx_queue": 1}}}
                       for t, v in zip((0, 10), rcvbuf)]
            (trial / "host.ndjson").write_text("".join(json.dumps(s) + "\n" for s in samples))
            return an.analyze(trial, 225)

    def test_reports_whole_run_drops_and_the_gate_fails_on_them(self):
        out = self.analyze((100, 117))
        self.assertEqual(out["window_ticks"], 0)
        self.assertEqual(out["drops"], {"whole": 17, "ramp": None, "minute": None, "tail": None})
        self.assertEqual(out["sndbuf_errors"]["whole"], 0)
        self.assertEqual(out["socket"]["drops"], 17)
        self.assertFalse(out["gates"]["socket_drops"])

    def test_measured_zero_passes_only_the_drop_gate(self):
        out = self.analyze((100, 100))
        self.assertTrue(out["gates"]["socket_drops"])
        self.assertFalse(out["gates"]["full_population"])
        self.assertFalse(out["all_but_rtt"])

    def test_no_host_samples_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            (trial / "server").mkdir()
            columns = ["utc_ns", "mono_ns", "work_ns", "budget_pct", *an.INT_COLS]
            (trial / "server/ticks.csv").write_text(",".join(columns) + "\n")
            out = an.analyze(trial, 225)
        self.assertIsNone(out["drops"])
        self.assertFalse(out["gates"]["socket_drops"])


if __name__ == "__main__":
    unittest.main()
