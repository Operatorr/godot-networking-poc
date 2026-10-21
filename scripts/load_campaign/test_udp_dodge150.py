"""Candidate identity and bounded journal wiring checks; no network/workloads."""
import inspect
import io
import json
import pathlib
import unittest
from unittest import mock
import udp_dodge150 as live
import udp_capacity150 as baseline
import udp_generator_profile_journal as journal
from udp_generator_profile_fixed_details import sockets

class DodgeTests(unittest.TestCase):
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
        self.assertIn("/udp_dodge150.py validate",source)
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

if __name__=='__main__':unittest.main()
