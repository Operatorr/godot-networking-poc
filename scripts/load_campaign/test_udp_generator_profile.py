"""No remote workloads: byte journals, frozen collection, identity and schedules."""
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import udp_generator_profile as controller
import udp_generator_profile_record as recorder
from udp_generator_profile_journal import scan, message

class GeneratorProfileTests(unittest.TestCase):
    def test_message_encodings(self):
        for value in ('oversized packet',list(b'oversized packet')):
            self.assertEqual(message({'MESSAGE':value}),'oversized packet')
        self.assertEqual(message({'MESSAGE':[255]}),'\ufffd')

    def test_streaming_counts_survive_prefix_limit(self):
        rows=[{'MESSAGE':'oversized packet','__REALTIME_TIMESTAMP':'1000000'},
              {'MESSAGE':list(b'send error'),'__REALTIME_TIMESTAMP':'2000000'},
              {'MESSAGE':'x','__REALTIME_TIMESTAMP':'3000000'}]
        lines=[(json.dumps(r)+'\n').encode() for r in rows];output=io.BytesIO()
        result=scan(iter(lines),output,{'full':(0,4*10**9),'steady':(2*10**9,3*10**9)},len(lines[0]))
        self.assertEqual(output.getvalue(),lines[0]);self.assertEqual(result['records'],3)
        self.assertEqual(result['periods']['steady']['counts'],{'records':1,'send':1})
        self.assertEqual(result['message_byte_arrays'],1);self.assertFalse(result['complete'])

    def test_frozen_collect_and_swarm_semantics(self):
        import inspect,udp_capacity150
        self.assertEqual(inspect.getsource(controller.collect),inspect.getsource(udp_capacity150.collect))
        self.assertEqual(inspect.getsource(controller.swarm),inspect.getsource(udp_capacity150.swarm))
        self.assertEqual(controller.COLLECTOR_REVISION,'994cce8c7cb2f689cd59f4d09e93e270057aba7e')
        self.assertEqual((controller.RAMP_SECONDS,controller.STEADY_SECONDS),(180,360))

    def test_expired_profile_cannot_start_or_backfill(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(recorder,'identity',return_value={'exe_sha256':recorder.EXPECTED}), mock.patch.object(recorder.subprocess,'Popen') as popen:
                recorder.record(1,pathlib.Path(d)/'early',0,0)
                popen.assert_not_called()
                s=json.loads((pathlib.Path(d)/'early/profile-status.json').read_text())
                self.assertEqual(s['error'],'entire-window-missed')

    def test_namespace_and_bound_guards(self):
        self.assertEqual(controller.NAMESPACE,'udp-generator-profile-20261021')
        self.assertEqual((recorder.SOFT,recorder.HARD),(30*1024**2,32*1024**2))
        with self.assertRaises(FileExistsError):recorder.record(1,pathlib.Path(tempfile.gettempdir()),0,0)

if __name__=='__main__':unittest.main()
