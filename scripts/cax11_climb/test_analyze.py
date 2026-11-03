#!/usr/bin/env python3
"""Window selection and counter splitting are what the climb's numbers rest on."""
import sys
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


if __name__ == "__main__":
    unittest.main()
