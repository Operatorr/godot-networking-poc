"""Fail-closed cell dispatch, immutable identity and complete received-AoI gates."""
import copy
import inspect
import io
import json
import pathlib
import types
import tempfile
import unittest
from unittest import mock

import clean_run as live
import clean_run_analysis as analysis
import udp_generator_profile_journal as journal


class CleanRunTests(unittest.TestCase):
    def setUp(self):
        self.cell=dict(namespace='clean-strategy150-r1-20261022',population=150,behavior='strategy',
            revision='487b6d9ad21e6d2fd1b1a9cf2b146ef454e9329a',game_sha256='a'*64,bot_sha256='b'*64)
        live.configure_cell(self.cell)

    def test_future_cells_and_rejected_invalid_specs(self):
        live.configure_cell(self.cell|dict(population=200,behavior='movement',namespace='clean-movement200-r2'))
        self.assertEqual((live.POPULATION,live.BEHAVIOR),(200,'movement'))
        self.assertIn('/omega-clean-movement200-r2/',live.EXPERIMENT_BINARIES['bots'])
        for update in ({'population':0},{'population':501},{'population':True},{'namespace':'../old'},
                       {'behavior':'unknown'},{'revision':'HEAD'},{'game_sha256':''}):
            with self.assertRaises(ValueError):live.configure_cell(self.cell|update)

    def test_remote_dispatch_never_falls_through_to_workload(self):
        with mock.patch.object(live,'controller') as controller,mock.patch.object(live,'journal') as export:
            live.dispatch(types.SimpleNamespace(mode='journal',since_ns=1,until_ns=2))
            export.assert_called_once_with(1,2);controller.assert_not_called()
        with mock.patch.object(live,'verify') as verify,mock.patch.object(live,'controller') as controller:
            live.dispatch(types.SimpleNamespace(mode='verify'))
            verify.assert_called_once_with('final');controller.assert_not_called()

    def test_both_source_and_config_required_in_every_runtime(self):
        row={'source_identity':dict(revision=live.CANDIDATE_REVISION,status='',game_sha256='a'*64,bot_sha256='b'*64),
             'config_sha256':'0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370',
             'identity':dict(MainPID='42',InvocationID='same',ActiveState='active',NRestarts='0'),
             'process':dict(pid=42,start_ticks=123,exe_path=live.EXPERIMENT_BINARIES['game'],exe_sha256='a'*64),
             'exe_sha256':'a'*64,'sockets':'pid=42, rb4194304 tb4194304 d0)'}
        live.validate_game_runtime(row,row,fresh=True)
        for section,key,value in [('source_identity','status',' M rust/server/src/main.rs'),
            ('source_identity','revision','0'*40),('source_identity','bot_sha256','c'*64),
            ('process','start_ticks',124),('identity','InvocationID','new')]:
            bad=copy.deepcopy(row);bad[section][key]=value
            with self.assertRaises(RuntimeError):live.validate_game_runtime(bad,row)
        with self.assertRaises(RuntimeError):live.validate_game_runtime(row|{'config_sha256':'0'*64})
        with self.assertRaises(RuntimeError):live.validate_game_runtime(row|{'source_identity':None})

    def test_audit_disabled_and_once_only_launch_and_cell_dispatch(self):
        source=inspect.getsource(live.controller)
        self.assertIn("local.mkdir(mode=0o700, exist_ok=False)",source)
        self.assertEqual(source.count("'-swarm --uid=deploy"),1)
        self.assertIn('UnsetEnvironment=OMEGA_AOI_AUDIT',source)
        self.assertNotIn('Environment=OMEGA_AOI_AUDIT=1',source)
        self.assertNotIn('head -1 ',source)
        self.assertIn("str(POPULATION), '--behavior', BEHAVIOR",source)
        self.assertIn('publish_file(copy,ssh,role',source)
        self.assertIn('validate_source_identity(b.get',source)

    def test_journal_byte_arrays_count_beyond_raw_retention(self):
        records=[dict(MESSAGE=list(b'oversized warning'),__REALTIME_TIMESTAMP=str(i)) for i in range(1,4)]
        r=journal.scan([json.dumps(v).encode()+b'\n' for v in records],io.BytesIO(),{'steady':(0,4000)},limit=1)
        self.assertEqual(r['periods']['steady']['counts']['oversized'],3)
        self.assertEqual(r['message_byte_arrays'],3);self.assertEqual(r['retained_bytes'],0)
        with mock.patch.object(journal,'export') as export:
            live.journal(1,2);export.assert_called_once_with(pathlib.Path(live.REMOTE)/'game',1,2)

    def report(self):
        return dict(per_bot=[dict(bot_id=i,aoi_matched_positions=20,aoi_unknown_positions=0) for i in (1,2)],
            regression_assertions=[dict(name='aoi_cull',passed=True,skipped=False,
                details=dict(threshold=1150,eligible_bots=2,violators=[],unknown_bots=[]))])

    def test_received_aoi_unknown_missing_and_any_actual_violation_fail(self):
        report=self.report();r=analysis.received_aoi(report,2)
        self.assertTrue(r['strict_default_pass'] and r['all_peer_zero_unknown'] and r['no_actual_above_1150'])
        report['per_bot'][0]['aoi_unknown_positions']=1
        self.assertFalse(analysis.received_aoi(report,2)['all_peer_zero_unknown'])
        report=self.report();del report['per_bot'][0]['aoi_unknown_positions']
        self.assertFalse(analysis.received_aoi(report,2)['all_peer_zero_unknown'])
        report=self.report();report['regression_assertions'][0]['details']['violators']=[dict(bot_id=1,max_distance=1150.0001)]
        self.assertFalse(analysis.received_aoi(report,2)['no_actual_above_1150'])
        report=self.report();report['regression_assertions'][0]['details']['threshold']=1200
        self.assertFalse(analysis.received_aoi(report,2)['strict_default_pass'])
        self.assertFalse(analysis.received_aoi({},2)['all_peer_zero_unknown'])


    def test_clean_classification_requires_final_snapshot_reconciliation(self):
        live.configure_cell(self.cell|dict(population=2))
        zero={k:0 for k in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')}
        udp={k:0 for k in ('RcvbufErrors','SndbufErrors','InErrors','MemErrors','InCsumErrors')}
        report=self.report()
        for row in report['per_bot']:row.update(state_updates_received=100,stale_snapshots_ignored=1)
        observed=[dict(boundary=b,bots=[dict(id=i,snapshots=100,stale_snapshots_ignored=1) for i in (1,2)]) for b in ('start','end')]
        def full():
            return dict(gates={'existing_campaign_gates':True,'complete_300s_common_coverage':True},collector_valid=True,generator_valid=True,
                full_workload_bot_errors=dict(zero),per_bot=[dict(id=i,errors_delta=dict(zero)) for i in (1,2)],
                journal_errors={p:dict(oversized_warnings=0,panics=0,suppressed_notice_count=0) for p in ('full_workload','steady_window')},
                hosts={role:dict(all_observed_socket_drop_sum=0,all_host_udp_delta=dict(udp)) for role in ('game','bots')},
                server_errors={p:dict(decode_errors=0,send_errors=0) for p in ('full_workload','steady_window')},
                periods={'full_workload':{'transport':{'counters':dict(send_errors=0,receive_errors=0,zero_byte_sends=0)}}})
        with mock.patch.object(analysis.base,'load',return_value=report),mock.patch.object(analysis.base,'rows',return_value=observed):
            clean=full();analysis.augment_clean_gates(clean,pathlib.Path('/unused'))
            self.assertEqual(clean['classification'],'clean-cell-pass')
            unobserved=full();unobserved['gates']['complete_300s_common_coverage']=False
            analysis.augment_clean_gates(unobserved,pathlib.Path('/unused'))
            self.assertFalse(unobserved['gates']['steady_window_oversized_panics_suppression_zero'])
            self.assertEqual(unobserved['classification'],'valid-failure')
            report['per_bot'][0]['state_updates_received']=101
            missing=full();analysis.augment_clean_gates(missing,pathlib.Path('/unused'))
            self.assertEqual(missing['classification'],'valid-failure')
            self.assertFalse(missing['gates']['full_replication_counters_cover_final_snapshot'])
            self.assertIsNone(missing['highest_passing_population_this_observation'])


    def test_deficits_retain_real_collector_counts_and_no_cause(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            directory=pathlib.Path(temp)
            for role in ('game','bots'):
                folder=directory/role;folder.mkdir()
                (folder/'port-bot.csv').write_text('port,bot_id\n4001,1\n')
                (folder/'flow-summary.json').write_text(json.dumps(dict(wire_input_counts_by_port={'4001':8900},window={'start':10,'end':300000000010})))
                (folder/'parser-status.json').write_text('{"status":"eof"}')
            full={'per_bot':[dict(id=1,offered_input_hz=30,inputs=[50,9050],wire_input_hz={'game':8900/300,'bots':8900/300})]}
            result=analysis.wire_deficits(full,directory)
            self.assertEqual(result[0]['hosts']['game']['exact_window_input_commands'],8900)
            self.assertEqual(result[0]['hosts']['bots']['mapped_port'],4001)
            self.assertIsNone(result[0]['cause'])
            full['per_bot'][0]['wire_input_hz']={'game':29.95,'bots':29.95}
            passing=analysis.wire_deficits(full,directory)
            self.assertEqual(passing[0]['failed_wire_hosts'],[])
            self.assertEqual(passing[0]['deficit_hosts'],['game','bots'])


class VerificationPreservationTests(unittest.TestCase):
    def test_repeated_verification_refuses_existing_outputs(self):
        import run
        with tempfile.TemporaryDirectory() as folder:
            checkout = pathlib.Path(folder)
            root = checkout/'deployment/hetzner/results'/live.NAMESPACE
            root.mkdir(parents=True)
            (root/'manifest.json').write_text('{}')
            for role in ('game','bots'):
                (root/(role+'-before.json')).write_text('{}')
            outputs = live.verification_paths(root, 'final')
            outputs['game'].write_bytes(b'prior host audit')
            with mock.patch.object(run, 'ROOT', checkout), mock.patch.object(run, 'ssh') as ssh:
                with self.assertRaises(FileExistsError):
                    live.verify()
                ssh.assert_not_called()
            fresh = live.verification_paths(root, 'parent-r2')
            self.assertNotEqual(outputs['summary'], fresh['summary'])
            self.assertEqual(outputs['game'].read_bytes(), b'prior host audit')


if __name__ == '__main__':unittest.main()
