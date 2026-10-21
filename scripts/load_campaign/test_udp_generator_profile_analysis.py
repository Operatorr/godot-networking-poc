"""Synthetic offline samples test count, weighting and clock/CPU attribution."""
import gzip
import json
import pathlib
import tempfile
import unittest
from udp_generator_profile_analysis import parse_profile, summarize_samples

class ProfileAnalysisTests(unittest.TestCase):
    def fixture(self,p):
        (p/'profile-status.json').write_text(json.dumps({'clock_ticks_per_second':100}))
        def stat(cpu):
            fields=['0']*22;fields[11]=str(cpu);fields[12]='0'
            return '1 (bot) '+' '.join(fields)
        anchors=[{'utc_ns':10_000_000_000,'monotonic_ns':1_000_000_000,'target_stat':stat(10)},
                 {'utc_ns':11_000_000_000,'monotonic_ns':2_000_000_000,'target_stat':stat(60)}]
        (p/'profile-clock.ndjson').write_text('\n'.join(map(json.dumps,anchors)))
        (p/'perf-script.txt').write_text('bot 1/1 1.100000000: 10000000 cpu-clock:\n    abc omega_load_test::bot::Bot::poll (/tmp/bot)\n    abd omega_load_test::main (/tmp/bot)\n\nbot 1/1 1.600000000: 20000000 cpu-clock:\n    abe [unknown] ([unknown])\n\n')
        with gzip.open(p/'perf-records.txt.gz','wt') as f:f.write('PERF_RECORD_SAMPLE\nPERF_RECORD_SAMPLE\n')
    def test_raw_counts_cpu_clock_and_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);self.fixture(p);samples,info=parse_profile(p)
            self.assertEqual(info['sample_count'],2);self.assertEqual(info['sampled_target_cpu_s'],.5)
            self.assertEqual(info['effective_samples_per_target_cpu_s'],4)
            self.assertEqual(samples[0]['utc_ns'],10_100_000_000)
            summary=summarize_samples(samples,0,2**63)
            self.assertEqual(summary['samples_with_named_leaf'],1)
            self.assertEqual(summary['top_self'][0]['symbol'],'[unknown]')
            self.assertAlmostEqual(summary['top_self'][0]['percent'],200/3)
    def test_mismatched_raw_sample_count_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);self.fixture(p)
            with gzip.open(p/'perf-records.txt.gz','wt') as f:f.write('PERF_RECORD_SAMPLE\n')
            with self.assertRaisesRegex(ValueError,'Raw/decoded'):parse_profile(p)

if __name__=='__main__':unittest.main()
