import unittest
import tempfile
import pathlib
import json
from aoi150_correlation import correlate, distance, analyze

class CorrelationTests(unittest.TestCase):
    def test_missing_and_ambiguous_rejected(self):
        a={'entity_position':[1000,0],'baseline':False}
        row={'x':'0','y':'0','max_distance':'1000','baseline':'false'}
        self.assertEqual(correlate(a,[])['classification'],'unknown-missing')
        self.assertEqual(correlate(a,[row,row])['classification'],'unknown-ambiguous')
        self.assertEqual(correlate(a,[row])['classification'],'legacy-mixed-time-false-positive')
        self.assertEqual(correlate(a,[row])['authoritative_distance_f32'],1000)
        self.assertEqual(correlate(a,[row|{'x':'-200','max_distance':'1200'}])['classification'],'authoritative-violation')
    def test_f32_rounding(self):
        self.assertEqual(distance([0,0],[3,4]),5)
        self.assertEqual(distance([16777216,0],[16777217,0]),0)

class EvidenceTests(unittest.TestCase):
    def fixture(self, root, sample_ns=20, deltas=1, duplicate=False):
        (root/'game').mkdir();(root/'bots').mkdir()
        (root/'game/ticks.csv').write_text('tick,utc_ns\n1,10\n')
        header='tick,server_ms,observer,x,y,baseline,full_request,records,positions,max_distance\n'
        row='1,5,1,0,0,false,false,1,1,1000\n'
        (root/'game/aoi.csv').write_text(header+row*(2 if duplicate else 1))
        assertion=[{'name':'aoi_cull','passed':False,'message':'unknown same-Snapshot center'}]
        report={'per_bot':[{'bot_id':1,'aoi_anomalies':[{'observer_id':1,'snapshot_tick':1,'server_ms':5,'entity_position':[1000,0],'baseline':False,'legacy_distance':1200}],
            'aoi_matched_positions':0,'aoi_unknown_positions':1,'max_observed_entity_distance':0,'legacy_max_observed_entity_distance':1200}],
            'assertions':assertion}
        (root/'bots/bot.json').write_text(json.dumps(report))
        (root/'game/server.ndjson').write_text(json.dumps({'utc_ns':sample_ns,'baselines':0,'deltas':deltas,'players':[],'send_errors':0})+'\n')
        return assertion

    def test_emission_pass_does_not_upgrade_unknown_bot_assertion(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);assertion=self.fixture(root)
            result=analyze(root,{'start':5,'end':15})
            self.assertTrue(result['authoritative_emission_validated'])
            self.assertEqual(result['strict_assertions_unmodified'],assertion)
            self.assertEqual(result['bot_lifetime']['unknown_positions'],1)
            self.assertEqual(result['legacy_anomalies'][0]['period'],'steady')

    def test_unaccounted_final_tail_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);self.fixture(root,deltas=0)
            self.assertFalse(analyze(root,{'start':5,'end':15})['authoritative_emission_validated'])

    def test_metrics_cannot_use_future_tick_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);self.fixture(root,sample_ns=9)
            result=analyze(root,{'start':5,'end':15})
            self.assertFalse(result['authoritative_emission_validated'])
            self.assertFalse(result['metric_reconciliation']['samples'][0]['timestamp_consistent'])

    def test_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);self.fixture(root,duplicate=True,deltas=2)
            result=analyze(root,{'start':5,'end':15})
            self.assertFalse(result['all_retained_anomalies_uniquely_attributed'])
            self.assertFalse(result['authoritative_emission_validated'])

if __name__=='__main__':unittest.main()
