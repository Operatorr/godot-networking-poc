"""Candidate identity and bounded journal wiring checks; no network/workloads."""
import inspect
import io
import json
import pathlib
import unittest
from unittest import mock
import udp_send150 as live
import udp_capacity150 as baseline
import udp_generator_profile_journal as journal
from udp_generator_profile_fixed_details import sockets

class SendTests(unittest.TestCase):
    def test_candidate_path_and_hash_reject_control(self):
        spec={'argv':[live.EXPERIMENT_BINARIES['bots']]}
        fake=mock.Mock();fake.hexdigest.return_value=live.EXPECTED_BOT
        with mock.patch.object(pathlib.Path,'read_bytes',return_value=b'candidate'),mock.patch.object(live.hashlib,'sha256',return_value=fake):
            live.validate_invocation(spec)
            with self.assertRaises(RuntimeError):live.validate_invocation({'argv':[live.CONTROL_BINARIES['bots']]})
            fake.hexdigest.return_value=live.EXPECTED_CONTROL['bots']
            with self.assertRaises(RuntimeError):live.validate_invocation(spec)
        self.assertNotEqual(live.EXPECTED_BOT,live.EXPECTED_CONTROL['bots'])
        self.assertRegex(live.EXPECTED_BOT,r'^[0-9a-f]{64}$')

    def test_runtime_identity_rejects_wrong_hash_path_start(self):
        row={'pid':9,'start_ticks':123,'exe_sha256':live.EXPECTED_BOT,'exe_path':live.EXPERIMENT_BINARIES['bots']}
        live.validate_bot_identity(row,row)
        for update in ({'exe_sha256':live.EXPECTED_CONTROL['bots']},{'exe_path':live.CONTROL_BINARIES['bots']},{'start_ticks':124},{'pid':10}):
            with self.assertRaises(RuntimeError):live.validate_bot_identity(row|update,row)

    def test_live_call_sites_and_no_sampler(self):
        source=inspect.getsource(live)
        self.assertIn('validate_invocation(spec)',inspect.getsource(live.swarm))
        self.assertIn("validate_bot_identity(b['bot_identity']",inspect.getsource(live.controller))
        self.assertIn("/udp_send150.py validate",source)
        for forbidden in ('perf record','profile_failure','profile-supervisor','udp_generator_profile_record'):
            self.assertNotIn(forbidden,source)
        self.assertEqual(inspect.getsource(live.collect),inspect.getsource(baseline.collect))
        self.assertEqual((live.RAMP_SECONDS,live.STEADY_SECONDS),(180,360))
        self.assertIn('publish_file(copy,ssh,role',source)

    def test_actual_journal_dispatch_and_complete_counts_after_prefix(self):
        with mock.patch.object(journal,'export') as export:
            live.journal(1,2)
            export.assert_called_once_with(pathlib.Path(live.REMOTE)/'game',1,2)
        records=[{'MESSAGE':list(b'oversized warning'),'__REALTIME_TIMESTAMP':str(i),'_SYSTEMD_INVOCATION_ID':'same'} for i in range(1,4)]
        output=io.BytesIO()
        result=journal.scan([json.dumps(r).encode()+b'\n' for r in records],output,{'steady':(0,4000)},limit=1)
        self.assertEqual(result['periods']['steady']['counts']['oversized'],3)
        self.assertEqual(result['message_byte_arrays'],3)
        self.assertFalse(result['complete'])
        self.assertEqual(result['retained_bytes'],0)

    def test_missing_pid_is_unknown(self):
        row='UNCONN uid:1000 ino:42 cgroup:/system.slice/omega-example-swarm.service\n skmem:(r12,rb212992,t0,tb212992,f0,w0,o0,bl0,d0)\n'
        self.assertIsNone(sockets(row)[0]['pid'])
        self.assertEqual(sockets(row)[0]['r'],12)


    def test_exact_game_candidate_is_not_old_build(self):
        self.assertNotEqual(live.EXPECTED_CANDIDATE,live.OLD_GAME_SHA)
        self.assertRegex(live.EXPECTED_CANDIDATE,r'^[0-9a-f]{64}$')
        self.assertEqual(live.CANDIDATE_REVISION,'e27db2d3c50b3b1dd550a32ed40f7a64526a4513')

    def game(self):
        return {'identity':{'MainPID':'42','InvocationID':'new','ActiveState':'active','NRestarts':'0'},
                'process':{'pid':42,'start_ticks':123,'exe_path':live.EXPERIMENT_BINARIES['game'],'exe_sha256':live.EXPECTED_CANDIDATE},
                'exe_sha256':live.EXPECTED_CANDIDATE,
                'sockets':'users:(("omega-server",pid=42,fd=9))\n skmem:(r0,rb4194304,t0,tb4194304,f0,w0,o0,bl0,d0)'}

    def test_actual_game_runtime_validation(self):
        import copy
        row=self.game();live.validate_game_runtime(row,row,fresh=True)
        for target,key,value in [('process','exe_path',live.OLD_GAME),('process','exe_sha256',live.OLD_GAME_SHA),('process','start_ticks',124),('identity','MainPID','43'),('identity','InvocationID','restart')]:
            bad=copy.deepcopy(row);bad[target][key]=value
            with self.assertRaises(RuntimeError):live.validate_game_runtime(bad,row)
        for k,v in [('exe_sha256',live.OLD_GAME_SHA),('sockets',row['sockets'].replace('tb4194304','tb524288')),('sockets',row['sockets'].replace('rb4194304','rb524288'))]:
            with self.assertRaises(RuntimeError):live.validate_game_runtime(row|{k:v},row)
        with self.assertRaises(RuntimeError):live.validate_game_runtime(row|{'sockets':row['sockets'].replace('d0)','d1)')},fresh=True)
        source=inspect.getsource(live.controller)
        self.assertIn('validate_game_runtime(fresh',source)
        self.assertIn('validate_game_runtime(g, fresh)',source)
        self.assertIn("result['process']=identity(int(pid))",inspect.getsource(live.status))

    def test_config_only_send_changes(self):
        original=json.loads((pathlib.Path(__file__).resolve().parents[2]/'deployment/server_config.loadtest.json').read_text())
        comparator=dict(original,udp_receive_buffer_bytes=2097152)
        raw=(json.dumps(comparator,indent=2)+'\n').encode()
        config,proof=live.make_config(raw)
        self.assertEqual(config,dict(comparator,udp_send_buffer_bytes=2097152))
        self.assertEqual(proof['semantic_diff'],{'udp_send_buffer_bytes':{'before':None,'after':2097152}})
        with self.assertRaises(RuntimeError):live.make_config(raw+b' ')

    def test_startup_requests_and_effective_both_checked(self):
        log='requested_receive_bytes=2097152 requested_send_bytes=2097152 effective_receive_bytes=4194304 effective_send_bytes=4194304 ENet UDP socket buffers initialized'
        live.validate_startup(log)
        for key in ('requested_receive_bytes','requested_send_bytes','effective_receive_bytes','effective_send_bytes'):
            with self.assertRaises(RuntimeError):live.validate_startup(log.replace(key+'=',key+'=0'))
        self.assertIn('validate_startup(',inspect.getsource(live.controller))

if __name__=='__main__':unittest.main()
