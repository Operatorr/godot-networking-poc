"""A delayed paired reply must not turn fresh-at-acquisition rows into stale collectors."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import clean_run as live


class DelayedPollTests(unittest.TestCase):
    def run_monitor(self, stale_role=None, never_fresh=False):
        live.configure_cell(dict(namespace='clean-delayed-poll-test', population=2, behavior='combat',
                                 revision='a'*40, game_sha256='b'*64, bot_sha256='c'*64))
        now = 1_000_000_000_000
        calls = {'game': 0, 'bots': 0}
        identity = dict(pid=42, start_ticks=123, exe_sha256='c'*64,
                        exe_path=live.EXPERIMENT_BINARIES['bots'])

        def ssh(role, command):
            self.assertTrue(command.endswith('status --role '+role))
            calls[role] += 1
            delayed = calls[role] == 1 or never_fresh
            # Retained R2 ages: both recorders fresh at acquisition, but their
            # observations age while waiting for the paired status commands.
            lag = (41_218_787_521 if role == 'game' else 13_265_456_527) if delayed else 0
            stamp = now-lag
            age = 11_000_000_000 if stale_role == role else (137_164_362 if role == 'game' else 917_282_688)
            row = dict(utc_ns=stamp, parser={'status': 'running'}, capture_resource=None,
                       host_fresh=True, mapping=[[4001, 1], [4002, 2]])
            if role == 'game':
                row.update(server=dict(utc_ns=stamp-age, players=[1, 2]), measurement_bytes=100)
            else:
                row.update(phase=dict(phase2_utc_ns=now-100_000_000_000),
                           guard=None if delayed else dict(reason=None, exit=1),
                           bot_identity=identity, bots_stamp=stamp-age,
                           sockets='omega-load-test\n skmem:(r0,rb212992,t0,tb212992)\n'
                                   'omega-load-test\n skmem:(r0,rb212992,t0,tb212992)')
            return json.dumps(row)

        manifest = dict(window=dict(start=now-37_573_481_182, end=now+262_426_518_818))
        monotonic = iter(range(0, 2000, 56))
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(live, 'validate_source_identity'), \
             mock.patch.object(live, 'validate_game_runtime'), \
             mock.patch.object(live.time, 'time_ns', return_value=now), \
             mock.patch.object(live.time, 'monotonic', side_effect=lambda:next(monotonic)), \
             mock.patch.object(live.time, 'sleep'):
            live.monitor_workload(pathlib.Path(tmp), manifest, {}, ssh, None)
            polls = [json.loads(line) for line in (pathlib.Path(tmp)/'status-polls.ndjson').read_text().splitlines()]
        return manifest, calls, polls

    def test_r2_delayed_pair_requeries_both_hosts_before_deciding(self):
        result, calls, polls = self.run_monitor()
        self.assertNotIn('controller_abort', result)
        self.assertEqual(result['guard_result'], dict(reason=None, exit=1))
        self.assertEqual(calls, dict(game=2, bots=2))
        self.assertEqual(result['expired_status_refreshes'], 1)
        self.assertEqual(polls[0]['expired_status_roles'], ['game', 'bots'])

    def test_actually_stale_game_row_still_fails_even_if_reply_is_delayed(self):
        result, calls, _ = self.run_monitor(stale_role='game')
        self.assertEqual(result['controller_abort'], 'game-observation-stale-over-10s')
        self.assertEqual(calls, dict(game=1, bots=1))

    def test_actually_stale_bot_row_still_fails_even_if_reply_is_delayed(self):
        result, calls, _ = self.run_monitor(stale_role='bots')
        self.assertEqual(result['controller_abort'], 'bot-observation-stale-over-10s')
        self.assertEqual(calls, dict(game=1, bots=1))

    def test_repeated_expired_replies_remain_bounded_by_overall_deadline(self):
        result, calls, _ = self.run_monitor(never_fresh=True)
        self.assertEqual(result['controller_abort'], 'overall-time-limit')
        self.assertLessEqual(calls['game'], 10)
        self.assertEqual(calls['game'], calls['bots'])
