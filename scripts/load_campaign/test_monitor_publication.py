"""Exercise the real monitor loop with the retained R3 publication delay."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import clean_run as live

class PublicationMonitorTests(unittest.TestCase):
    def run_monitor(self, *, sample_age_ns=565_104_653, bot_age_ns=None, publication_seconds=17.950328):
        live.configure_cell(dict(namespace='clean-monitor-test',population=2,behavior='idle',
            revision='a'*40,game_sha256='b'*64,bot_sha256='c'*64))
        phase=1_000_000_000_000
        clock={'ns':phase+3_000_000_000,'polls':0}
        publications=[]
        identity=dict(exe_sha256='c'*64,exe_path=live.EXPERIMENT_BINARIES['bots'])
        def ssh(role, command):
            self.assertIn(' status --role ',command)
            if role=='game':
                clock['polls']+=1
                if clock['polls']>1: clock['ns']=phase+361_000_000_000
            common=dict(parser={'status':'running'},capture_resource=None,host_fresh=True,mapping=[(4001,1),(4002,2)])
            if role=='game':return json.dumps(common|dict(server={'utc_ns':clock['ns']-sample_age_ns,'players':[1,2]},measurement_bytes=100))
            return json.dumps(common|dict(phase={'phase2_utc_ns':phase},guard=({'reason':None,'exit':1} if clock['polls']>1 else None),
                bot_identity=identity,sockets='omega-load-test\n skmem:(r0,rb212992,t0,tb212992)\nomega-load-test\n skmem:(r0,rb212992,t0,tb212992)',
                bots_stamp=clock['ns']-(sample_age_ns if bot_age_ns is None else bot_age_ns)))
        def publish(copy, ssh, role, source, destination):
            publications.append(role)
            clock['ns']+=int(publication_seconds*1e9/2)
        manifest={}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(live,'validate_source_identity'), \
             mock.patch.object(live,'validate_game_runtime'), mock.patch.object(live,'publish_file',side_effect=publish), \
             mock.patch.object(live.time,'time_ns',side_effect=lambda:clock['ns']), \
             mock.patch.object(live.time,'monotonic',side_effect=lambda:clock['ns']/1e9), mock.patch.object(live.time,'sleep'):
            live.monitor_workload(pathlib.Path(temp),manifest,{},ssh,None)
        return manifest,clock['polls'],publications

    def test_r3_publication_delay_requires_new_status_before_freshness_decision(self):
        result,polls,published=self.run_monitor()
        self.assertNotIn('controller_abort',result)
        self.assertGreaterEqual(polls,2)
        self.assertEqual(published,['game','bots'])
        self.assertEqual(result['guard_result'],{'reason':None,'exit':1})

    def test_actually_stale_sample_aborts_before_publication(self):
        result,polls,published=self.run_monitor(sample_age_ns=11_000_000_000)
        self.assertEqual(result['controller_abort'],'game-observation-stale-over-10s')
        self.assertEqual(published,[])

    def test_publication_missing_required_lead_time_fails_closed(self):
        result,polls,published=self.run_monitor(publication_seconds=55)
        self.assertEqual(result['controller_abort'],'window-publication-missed-lead-time')
        self.assertEqual(polls,1)

    def test_actually_stale_bot_sample_also_aborts_before_publication(self):
        result,polls,published=self.run_monitor(bot_age_ns=11_000_000_000)
        self.assertEqual(result['controller_abort'],'bot-observation-stale-over-10s')
        self.assertEqual(published,[])
