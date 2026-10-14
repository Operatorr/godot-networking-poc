"""CPU normalization and post-collapse averages must not hide saturation."""
import unittest
import cpu_report


def sample(second, ticks, busy, starttime=1, steal=0):
    # Both cores advance by 100 ticks/s; busy is total execution across two cores.
    one = [busy // 2, 0, 0, second * 100 - busy // 2 - steal // 2, 0, 0, 0, steal // 2]
    total = [value * 2 for value in one]
    fields = ['R'] + ['0'] * 21
    fields[11] = str(ticks); fields[12] = '0'; fields[19] = str(starttime)
    return {'utc_ns': second * 10**9, 'monotonic_ns': second * 10**9, 'clock_ticks_s': 100,
            'stat': '\n'.join(name + ' ' + ' '.join(map(str, values)) for name, values in [('cpu', total), ('cpu0', one), ('cpu1', one)]),
            'processes': {'42': {'comm': 'omega-server\n', 'stat': '42 (omega-server) ' + ' '.join(fields)}}}


class CpuReportTests(unittest.TestCase):
    def test_one_busy_core_is_100_process_percent_but_half_two_core_host_capacity(self):
        first, last = sample(1, 100, 100), sample(2, 200, 200)
        point = cpu_report.interval(first, last)
        self.assertEqual(point['process_cpu_percent_one_core'], 100)
        self.assertEqual(point['host_execution_percent_capacity'], 50)
        self.assertEqual(point['host_execution_percent_one_core'], 100)
        self.assertEqual(point['busiest_core_execution_percent'], 50)

    def test_steal_is_not_executing_cpu(self):
        point = cpu_report.interval(sample(1, 100, 100, steal=0), sample(2, 150, 150, steal=50))
        self.assertEqual(point['host_execution_percent_capacity'], 25)
        self.assertEqual(point['steal_percent_capacity'], 25)

    def test_cpu_counter_reset_and_pid_reuse_do_not_create_false_peaks(self):
        self.assertIsNone(cpu_report.interval(sample(1, 100, 100), sample(2, 200, 200, starttime=2))['process_cpu_percent_one_core'])
        with self.assertRaises(ValueError):
            cpu_report.interval(sample(2, 200, 200), sample(1, 100, 100))

    def test_cpu_collapse_lowers_mean_but_peak_and_busy_duration_remain(self):
        a, b, c, d = sample(1, 100, 100), sample(2, 200, 200), sample(3, 200, 200), sample(4, 200, 200)
        summary, points = cpu_report.summarize_host([b, c], a, d)
        self.assertAlmostEqual(summary['matched_boundary']['process_cpu_percent_one_core'], 100 / 3)
        stats = summary['one_second_statistics']['process_cpu_percent_one_core']
        self.assertEqual(stats['max'], 100)
        self.assertEqual(stats['seconds_at_or_above_95_percent'], 1)
        self.assertEqual(stats['longest_contiguous_seconds_at_or_above_95_percent'], 1)

    def test_sampling_gaps_break_sustained_cpu_streaks(self):
        points = [{'utc_start_ns': a, 'utc_end_ns': b, 'interval_s': (b-a)/1e9, 'cpu': 100, 'usable_for_1hz_peaks': True}
                  for a,b in [(0,10**9),(2*10**9,3*10**9)]]
        self.assertEqual(cpu_report.percentiles(points, 'cpu')['longest_contiguous_seconds_at_or_above_95_percent'], 1)

    def test_tiny_boundary_interval_is_not_reported_as_instantaneous_peak(self):
        points = [{'utc_start_ns': 0, 'utc_end_ns': 10**7, 'interval_s': .01, 'cpu': 500, 'usable_for_1hz_peaks': False},
                  {'utc_start_ns': 10**7, 'utc_end_ns': 101*10**7, 'interval_s': 1, 'cpu': 50, 'usable_for_1hz_peaks': True}]
        self.assertEqual(cpu_report.percentiles(points, 'cpu')['max'], 50)


if __name__ == '__main__':
    unittest.main()
