"""Exercise the exact Strategy50 dispatch without starting a remote workload."""
import copy
import json
import pathlib
import unittest
from unittest.mock import patch

import clean_run as live
import native_diagnostic_r4 as reuse
from test_ordinary_combat100_r1 import cell as prior_cell

NS = 'clean-strategy50-r1-20261024'


def cell():
    return prior_cell() | dict(namespace=NS, population=50, behavior='strategy', evidence_profile='strategy50-compact-v1')


class Strategy50Round1Tests(unittest.TestCase):
    def test_real_load_dispatch_requires_exact_ordinary_v2_condition(self):
        proof = {role: dict(path='/home/deploy/omega-'+NS, revision=reuse.REVISION,
                           sha256=reuse.GAME_SHA, bot_sha256=reuse.BOT_SHA,
                           native_build_origin='bots',
                           game_artifact_mode='verified-existing-build-copy')
                 for role in ('game', 'bots')}
        with patch.object(pathlib.Path, 'exists', return_value=False), patch.object(
                pathlib.Path, 'read_text', return_value=json.dumps(proof)):
            live.load_cell(NS, 50, 'strategy')
            self.assertEqual(live.CELL, cell())
            self.assertTrue(live.compact_ordinary())
            self.assertEqual(live.measurement_limit_bytes(), 16*1024**2)
            for population, behavior in ((100, 'strategy'), (50, 'combat')):
                with self.assertRaises(ValueError):
                    live.load_cell(NS, population, behavior)
        for change in (dict(namespace=NS+'-retry'), dict(classification_version='strict-v1'),
                       dict(classification_version=None), dict(native_diagnostic='v1'),
                       dict(revision='0'*40), dict(bot_sha256='0'*64),
                       dict(game_sha256='0'*64), dict(measurement_preservation='copy'),
                       dict(evidence_profile='other'), dict(native_build_origin='game')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                live.configure_cell(cell() | change)
        missing = cell(); missing.pop('classification_version')
        with self.assertRaises(ValueError):
            live.configure_cell(missing)

    def test_reuse_and_release_round_are_exact_and_preserve_r1(self):
        row = dict(revision=reuse.REVISION, path='/home/deploy/omega-'+reuse.REUSE_NAMESPACE,
                   sha256=reuse.GAME_SHA, bot_sha256=reuse.BOT_SHA, native_build_origin='bots')
        proof = {role: copy.deepcopy(row) for role in ('game', 'bots')}
        reuse.validate_reuse(NS, reuse.REVISION, reuse.REUSE_NAMESPACE, proof)
        self.assertEqual(reuse.ROUND_NAMES[NS], 'ordinary-strategy50-r1')
        self.assertEqual(reuse.ROUND_NAMES[prior_cell()['namespace']], 'ordinary-combat100-r1')
        self.assertEqual(live.ORDINARY_SPECS[NS], (50, 'strategy', 'strategy50-compact-v1'))
        self.assertEqual(live.ORDINARY_SPECS[prior_cell()['namespace']], (100, 'combat', 'combat100-compact-v1'))
        with self.assertRaises(ValueError):
            reuse.validate_reuse(NS+'-retry', reuse.REVISION, reuse.REUSE_NAMESPACE, proof)


if __name__ == '__main__':
    unittest.main()
