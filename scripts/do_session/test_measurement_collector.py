"""The role collector's parsers against /proc-shaped fixtures, and the runner's new seams against real processes.

macOS has no /proc, so these fixtures are the only run the Linux paths have had here. They prove parsing and identity joins. A real Droplet's counters are for Gate A.
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / 'quick_stress'))
import sample_host  # noqa: E402

import guest_runner  # noqa: E402
import run_plan  # noqa: E402
import search  # noqa: E402

UDP = """   sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  100: 00000000:1F91 00000000:0000 07 00000000:00000200 00:00000000 00000000  1000        0 555001 2 0000000000000000 7
  101: 00000000:9C41 00000000:0000 07 00000010:00000000 00:00000000 00000000  1000        0 555002 2 0000000000000000 0
  102: 00000000:9C42 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 666000 2 0000000000000000 42
"""


class ProcTree(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix='omega-proc-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / 'net').mkdir()
        (self.root / 'net/udp').write_text(UDP)
        (self.root / 'net/udp6').write_text(UDP.splitlines()[0] + '\n')

    def own(self, pid, inodes):
        fd = self.root / str(pid) / 'fd'
        fd.mkdir(parents=True)
        for index, inode in enumerate(inodes):
            os.symlink('socket:[%s]' % inode, str(fd / str(index)))
        os.symlink('/dev/null', str(fd / '99'))

    def test_only_sockets_this_process_holds_are_attributed_to_it(self):
        self.own(77, ['555001', '555002'])
        table = sample_host.udp_table(str(self.root))
        rows = sample_host.owned_sockets(77, table, str(self.root))
        self.assertEqual([row['inode'] for row in rows], ['555001', '555002'])
        self.assertEqual(rows[0], dict(inode='555001', local='00000000:1F91', local_port=8081, drops=7, rx_queue=512, tx_queue=0))
        self.assertEqual(rows[1]['tx_queue'], 16)
        self.assertNotIn('666000', [row['inode'] for row in rows], 'another process\'s socket and its 42 drops stay out')

    def test_a_process_that_has_gone_has_no_socket_answer_rather_than_an_empty_one(self):
        self.assertIsNone(sample_host.owned_sockets(78, sample_host.udp_table(str(self.root)), str(self.root)))

    def test_per_thread_cpu_keeps_each_thread_by_name(self):
        for tid, name, user, system in ((10, 'swarm-0', 500, 100), (11, 'swarm 1', 700, 300)):
            task = self.root / '77/task' / str(tid)
            task.mkdir(parents=True)
            fields = ['S'] + ['0'] * 10 + [str(user), str(system)] + ['0'] * 30
            (task / 'stat').write_text('%d (%s) %s\n' % (tid, name, ' '.join(fields)))
        clock = os.sysconf('SC_CLK_TCK')
        cpu = sample_host.thread_cpu(77, str(self.root))
        self.assertEqual(cpu['swarm-0/10'], 600 / clock)
        self.assertEqual(cpu['swarm 1/11'], 1000 / clock)

    def test_memory_and_interface_counters_are_raw_and_absent_when_unknown(self):
        (self.root / 'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
        (self.root / 'vmstat').write_text('oom_kill 3\npgmajfault 9\n')
        (self.root / 'net/dev').write_text('Inter-|   Receive\n face |bytes\n  eth0: 100 2 0 1 0 0 0 0 300 4 0 2 0 0 0 0\n')
        facts = sample_host.memory_facts(str(self.root))
        self.assertEqual(facts['MemAvailable'], 409600)
        self.assertEqual(facts['oom_kill'], 3)
        self.assertNotIn('pswpin', facts, 'not reported is absent, never zero')
        self.assertEqual(sample_host.interface_counters(str(self.root))['eth0'], dict(rx_bytes=100, rx_packets=2, rx_errs=0, rx_drop=1, tx_bytes=300, tx_packets=4, tx_errs=0, tx_drop=2))
        self.assertEqual(sample_host.memory_facts(str(self.root / 'nowhere')), {})

    def test_a_cut_table_line_is_skipped_not_misread(self):
        self.assertEqual(sample_host.parse_proc_net_udp(UDP.splitlines()[0] + '\n  100: 00000000:1F91 trailing\n'), {})


class RealSampler(unittest.TestCase):
    def test_identity_rows_from_a_real_process(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix='omega-sampler-'))
        self.addCleanup(shutil.rmtree, root, True)
        holder = subprocess.Popen([sys.executable, '-c', 'import socket,time; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1",0)); print(s.getsockname()[1],flush=True); time.sleep(30)'], stdout=subprocess.PIPE)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        port = int(holder.stdout.readline())
        (root / 'pids').write_text('bot=%d\n' % holder.pid)
        sampler = subprocess.Popen([sys.executable, str(HERE.parent / 'quick_stress/sample_host.py'), '--out', str(root / 'out.ndjson'), '--pids', str(root / 'pids'), '--interval', '0.2', '--identity'])
        self.addCleanup(sampler.wait)
        self.addCleanup(sampler.kill)
        deadline = time.monotonic() + 15
        rows = []
        while time.monotonic() < deadline and len(rows) < 3:
            time.sleep(0.1)
            rows = [json.loads(line) for line in (root / 'out.ndjson').read_text().splitlines() if 'clock' in line]
        self.assertGreaterEqual(len(rows), 3)
        facts = rows[-1]['procs']['bot']
        self.assertEqual(facts['pid'], holder.pid)
        self.assertEqual(facts['start_id'], guest_runner.process_start_id(holder.pid), 'the same identity the supervisor records')
        self.assertIn(port, [item['local_port'] for item in facts['sockets']])
        self.assertLessEqual(rows[-1]['clock']['wall_before_ns'], rows[-1]['clock']['wall_after_ns'])
        self.assertEqual(rows[-1]['seq'], rows[-2]['seq'] + 1)
        self.assertGreater(rows[-1]['collector_ns'], 0)

    def test_a_plain_row_is_unchanged_without_the_flag(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix='omega-sampler-'))
        self.addCleanup(shutil.rmtree, root, True)
        (root / 'pids').write_text('bot=%d\n' % os.getpid())
        sampler = subprocess.Popen([sys.executable, str(HERE.parent / 'quick_stress/sample_host.py'), '--out', str(root / 'out.ndjson'), '--pids', str(root / 'pids'), '--interval', '0.1'])
        self.addCleanup(sampler.wait)
        self.addCleanup(sampler.kill)
        deadline = time.monotonic() + 15
        rows = []
        while time.monotonic() < deadline and len(rows) < 2:
            time.sleep(0.1)
            rows = (root / 'out.ndjson').read_text().splitlines()
        row = json.loads(rows[-1])
        self.assertNotIn('clock', row)
        self.assertNotIn('pid', row['procs']['bot'])


class RunnerSeams(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='omega-runner-')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.host = guest_runner.Host(self.root)

    def test_clock_answers_with_no_state(self):
        before = time.time_ns()
        document = guest_runner.cmd_clock(None, self.host)
        self.assertGreaterEqual(document['wall_ns'], before)
        self.assertEqual(document['boot_id'], guest_runner.boot_id())
        self.assertIsInstance(document['monotonic_ns'], int)

    def test_sampler_tail_ignores_a_cut_last_row(self):
        path = pathlib.Path(self.root) / 'sampler.ndjson'
        path.write_text('{"kind": "meta"}\n{"mono_s": 1}\n{"mono_s": 2}\n{"mono_s": 3, "cut')
        self.assertEqual(guest_runner.sampler_tail(path), (3, 2))
        self.assertEqual(guest_runner.sampler_tail(pathlib.Path(self.root) / 'absent'), (0, None))

    def test_sampler_socket_inodes_are_collected_for_the_ledger(self):
        path = pathlib.Path(self.root) / 'sampler.ndjson'
        path.write_text(json.dumps(dict(kind='meta')) + '\n' + json.dumps(dict(procs=dict(bot=dict(sockets=[dict(inode='1'), dict(inode='2')]), sampler=dict(alive=False)))) + '\n')
        self.assertEqual(guest_runner.sampler_socket_inodes(path), {'1', '2'})

    def test_a_process_declaring_a_polite_stop_gets_that_signal_first(self):
        script = pathlib.Path(self.root) / 'workload.py'
        script.write_text('import signal,sys,time\nsignal.signal(signal.SIGINT, lambda *_: (open("got-sigint","w").close(), sys.exit(0)))\nsignal.signal(signal.SIGTERM, lambda *_: sys.exit(9))\nopen("ready","w").close()\ntime.sleep(60)\n')
        run_dir = pathlib.Path(self.root) / 'runs/r1/game'
        run_dir.mkdir(parents=True)
        plan = dict(schema=guest_runner.PLAN_SCHEMA, session_id='s', fencing_token=1, run_id='r1', role='game', unit_mode=guest_runner.PROCESS_GROUP, unit='u', plan_digest='x', launch_not_after_wall=time.time() + 30,
                    grant=dict(id='0' * 32, ttl_s=30), bound_s=30, stop_by_wall=time.time() + 30, minimum_bound_s=0, stop_grace_s=5, watch_socket_port=None, sampler=None,
                    processes=[dict(name='game', primary=True, argv=[sys.executable, str(script)], stop_signal='SIGINT')])
        (run_dir / 'plan.json').write_text(json.dumps(plan))
        (pathlib.Path(self.root) / 'control/fence.json').write_text(json.dumps(dict(session_id='s', token=1, closed=None)))
        (pathlib.Path(self.root) / 'control/grants').mkdir()
        (pathlib.Path(self.root) / 'control/grants' / ('0' * 32 + '.json')).write_text(json.dumps(dict(grant_id='0' * 32, session_id='s', token=1, boot_id=guest_runner.boot_id(), clock_ns=guest_runner.grant_clock_ns())))
        supervisor = subprocess.Popen([sys.executable, str(HERE / 'guest_runner.py'), '--root', self.root, 'supervise', '--run-dir', str(run_dir)], env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.addCleanup(supervisor.wait)
        self.addCleanup(supervisor.kill)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not (run_dir / 'ready').exists():
            time.sleep(0.02)
        self.assertTrue((run_dir / 'ready').exists())
        (run_dir / 'stop.request').write_text(json.dumps(dict(reason='test')))
        while time.monotonic() < deadline and not (run_dir / 'result.json').exists():
            time.sleep(0.02)
        result = json.loads((run_dir / 'result.json').read_text())
        self.assertTrue((run_dir / 'got-sigint').exists())
        self.assertEqual(result['processes']['game']['returncode'], 0)
        self.assertFalse(result['killed'])


class Adapter(unittest.TestCase):
    MANIFEST = dict(workload=dict(behavior='strategy', difficulty=1.0, input_hz=30, seed=1, generator_threads=4, join_stagger_ms=100))

    def trial(self, target=100, hold=60):
        return search.Trial(run_id='r', ordinal=1, phase='coarse', target=target, repetition=1, hold_s=hold, predecessors=())

    def test_the_swarm_gets_every_accepted_control_explicitly(self):
        argv = run_plan.ReleaseAdapter().bot_process(self.MANIFEST, self.trial(), dict(game='203.0.113.10'))['argv']
        self.assertIn('--measured-window', argv)
        expected = {'--server': '203.0.113.10:8081', '--bots': '100', '--hold-s': '60', '--behavior': 'strategy', '--difficulty': '1.0', '--input-hz': '30', '--seed': '1', '--threads': '4', '--stagger': '100',
                    '--readiness-timeout-s': '60', '--evidence-dir': '{run_dir}/swarm', '--output': '{run_dir}/report.json'}
        for flag, value in expected.items():
            self.assertEqual(argv[argv.index(flag) + 1], value, flag)
        self.assertNotIn('--duration', argv)

    def test_the_readiness_bound_is_the_accepted_one(self):
        argv = run_plan.ReleaseAdapter().bot_process(self.MANIFEST, self.trial(target=500), dict(game='203.0.113.10'))['argv']
        self.assertEqual(argv[argv.index('--readiness-timeout-s') + 1], str(search.readiness_bound_s(500)))
        self.assertEqual(search.readiness_bound_s(500), 80.0)

    def test_the_game_keeps_create_only_evidence_and_a_polite_stop(self):
        process = run_plan.ReleaseAdapter().game_process(self.MANIFEST, self.trial(), dict(game='x'))
        self.assertEqual(process['env']['OMEGA_MEASURE_WINDOW_EVIDENCE'], '1')
        self.assertEqual(process['stop_signal'], 'SIGINT')

    def test_clean_exits_must_leave_the_recorders(self):
        adapter = run_plan.ReleaseAdapter()
        self.assertIn('swarm/window.json', adapter.required_on_clean_exit('bot'))
        self.assertIn('telemetry/final.json', adapter.required_on_clean_exit('game'))
        self.assertIn('--identity', adapter.sampler_process('bot')['argv'])

    def test_the_process_bound_covers_what_a_healthy_swarm_needs_past_its_hold(self):
        trial = self.trial()
        self.assertEqual(run_plan.swarm_bound_s(trial) - run_plan.workload_s(trial), 4.5)
        schema = json.loads((HERE / 'measurement_schema.json').read_text())['swarm_timing_ns']
        self.assertEqual(schema['publish_lead'] + schema['end_guard'] + schema['drain'], 4.5e9, 'the schema, the swarm and the budget say the same')


if __name__ == '__main__':
    unittest.main()
