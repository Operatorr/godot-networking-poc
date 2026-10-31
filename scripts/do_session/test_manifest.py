"""Manifest freezing rejects missing, changed, unsupported and silently substituted conditions."""
import unittest

import fixture_support as fx
import manifest as m


def freeze(conditions=None, preflight=None, when=fx.FROZEN_AT):
    return m.freeze_manifest(conditions or fx.conditions(), preflight or fx.preflight(), when)


def rejection(conditions=None, preflight=None, when=fx.FROZEN_AT):
    try:
        freeze(conditions, preflight, when)
    except m.ManifestError as error:
        return error.reasons
    raise AssertionError('manifest was frozen but a rejection was expected')


class FreezeTests(unittest.TestCase):
    def test_fixture_freezes_deterministically(self):
        first, sha1 = freeze()
        second, sha2 = freeze()
        self.assertEqual(sha1, sha2)
        self.assertEqual(m.manifest_sha256(first), sha1)
        self.assertEqual(first['schema'], m.MANIFEST_SCHEMA)
        self.assertEqual(first['session']['condition']['display'], 'premium-amd-1vcpu-1g')
        self.assertEqual(first['session']['condition']['nominal_monthly_usd'], 7.0)
        self.assertTrue(first['session']['condition']['name'].startswith('do-sgp-premium-amd-1vcpu-1g-public-'))
        self.assertEqual(first['quote']['roles']['game']['price_hourly_usd'], 0.01042)
        self.assertEqual(first['quote']['roles']['bot']['size_slug'], 's-4vcpu-8gb-amd')
        self.assertEqual(first['search_policy']['max_trials_per_condition'], 27)
        self.assertEqual(first['credentials']['controller_token_ref'],
                         'file:~/.config/omega-realm/digitalocean/controller.token')

    def test_verify_detects_any_change(self):
        manifest, sha = freeze()
        m.verify_manifest(manifest, sha)
        manifest['limits']['max_session_duration_s'] += 1
        with self.assertRaises(m.ManifestError):
            m.verify_manifest(manifest, sha)

    def test_canonical_json_is_order_independent(self):
        self.assertEqual(m.canonical_json({'b': 1, 'a': [1, 2]}), m.canonical_json({'a': [1, 2], 'b': 1}))


class RejectionTests(unittest.TestCase):
    def test_missing_limits_rejected(self):
        conditions = fx.conditions()
        del conditions['limits']['max_estimated_session_usd']
        self.assertTrue(any('max_estimated_session_usd' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        del conditions['limits']
        self.assertIn('missing limits', rejection(conditions))

    def test_missing_timing_basis_rejected(self):
        conditions = fx.conditions()
        del conditions['timing_basis']['process_reset_s']
        reasons = rejection(conditions)
        self.assertTrue(any('process_reset_s is absent' in r for r in reasons), reasons)

    def test_capacity_session_needs_calibrated_bootstrap_and_export(self):
        conditions = fx.conditions()
        conditions['timing_basis']['create_bootstrap_s'] = dict(seconds=900, basis='declared_conservative',
                                                                provenance='guess')
        reasons = rejection(conditions)
        self.assertTrue(any('must be calibrated before a capacity session' in r for r in reasons), reasons)
        conditions['session']['kind'] = 'calibration'
        conditions['evidence'].pop('durable_destination')
        freeze(conditions)   # a calibration session may run on declared conservative bounds

    def test_calibration_claim_without_evidence_rejected(self):
        conditions = fx.conditions()
        del conditions['timing_basis']['collection_export_s']['evidence_sha256']
        self.assertTrue(any('claims calibration without evidence_sha256' in r for r in rejection(conditions)))

    def test_unsupported_hardware_rejected(self):
        conditions = fx.conditions()
        conditions['roles']['game'].update(size_slug='s-1vcpu-1gb', cpu_class='regular')
        reasons = rejection(conditions)
        self.assertTrue(any('not an accepted game-host condition' in r for r in reasons), reasons)

    def test_silent_substitution_against_preflight_rejected(self):
        conditions = fx.conditions()
        conditions['roles']['game']['memory_mib'] = 2048   # claims 2 GiB on the 1 GiB slug
        self.assertTrue(any('does not match preflight' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['roles']['game']['image_id'] = 999999
        self.assertTrue(any('not in the preflight image inventory' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['roles']['game']['image_id'] = 'ubuntu-24-04-x64'
        self.assertTrue(any('numeric official image ID' in r for r in rejection(conditions)))
        preflight = fx.preflight()
        preflight['sizes'][0]['available'] = False
        self.assertTrue(any('not listed available' in r for r in rejection(preflight=preflight)))
        preflight = fx.preflight()
        preflight['sizes'][0]['price_hourly_usd'] = 0.02
        manifest, _ = freeze(preflight=preflight)
        self.assertEqual(manifest['quote']['roles']['game']['price_hourly_usd'], 0.02,
                         'prices come from the live preflight, not a table')

    def test_region_route_and_network_conditions_are_fixed(self):
        conditions = fx.conditions()
        conditions['roles']['bot']['region'] = 'nyc3'
        self.assertTrue(any('region must be sgp1' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['roles']['game']['public_route'] = 'vpc'
        self.assertTrue(any('public_route must be public-ipv4' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['roles']['game']['private_networking'] = True
        self.assertTrue(any('private_networking must be explicitly false' in r for r in rejection(conditions)))

    def test_generator_must_be_fixed_separate_4vcpu_8gib(self):
        conditions = fx.conditions()
        conditions['roles']['bot'].update(size_slug='s-2vcpu-2gb-amd', vcpus=2, memory_mib=2048, disk_gib=60)
        self.assertTrue(any('fixed separate 4-vCPU/8-GiB generator' in r for r in rejection(conditions)))

    def test_moving_or_dirty_source_rejected(self):
        conditions = fx.conditions()
        conditions['source']['benchmark_sha'] = 'master'
        self.assertTrue(any('full 40-hex commit SHA' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['source']['clean'] = False
        self.assertTrue(any('source.clean must be true' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['source']['reviewed'] = False
        self.assertTrue(any('unreviewed source is rejected' in r for r in rejection(conditions)))

    def test_workload_schema_is_frozen(self):
        conditions = fx.conditions()
        conditions['workload']['generator_threads'] = 2
        self.assertTrue(any('generator_threads' in r and 'frozen value' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['workload']['min_configured_players'] = 100
        self.assertTrue(any('min_configured_players' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['workload']['extra_seed'] = 7
        self.assertTrue(any('not part of the frozen workload schema' in r for r in rejection(conditions)))

    def test_credential_values_rejected_references_accepted(self):
        conditions = fx.conditions()
        conditions['credentials']['controller_token_ref'] = 'dop_v1_' + 'a' * 64
        reasons = rejection(conditions)
        self.assertTrue(any('credential value detected' in r for r in reasons), reasons)
        self.assertTrue(any('never a value' in r for r in reasons), reasons)
        conditions = fx.conditions()
        conditions['ssh_key']['private_key_ref'] = '-----BEGIN OPENSSH PRIVATE KEY-----\nabc'
        self.assertTrue(any('credential value detected' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['credentials']['watchdog_token_ref'] = 'plain-string-not-a-reference'
        self.assertTrue(any('watchdog_token_ref' in r for r in rejection(conditions)))

    def test_ssh_key_must_match_registered_public_key(self):
        conditions = fx.conditions()
        conditions['ssh_key']['fingerprint_sha256'] = 'SHA256:other'
        self.assertTrue(any('does not match the registered key' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['ssh_key']['id'] = 1
        self.assertTrue(any('not a registered public key' in r for r in rejection(conditions)))

    def test_conditional_ram_tier_requires_memory_pressure_and_explicit_admission(self):
        conditions = fx.conditions()
        conditions['roles']['game'].update(size_slug='s-1vcpu-2gb-amd', memory_mib=2048, disk_gib=50)
        reasons = rejection(conditions)
        self.assertTrue(any('requires recorded memory_pressure_evidence' in r for r in reasons), reasons)
        self.assertTrue(any('explicit_conditional_admission' in r for r in reasons), reasons)
        conditions['explicit_conditional_admission'] = True
        conditions['memory_pressure_evidence'] = dict(source_condition='s-1vcpu-1gb-amd', session_id='do-cap-1v1g-x',
                                                      indicators=['cpu_saturation'], evidence_sha256='8' * 64)
        reasons = rejection(conditions)
        self.assertTrue(any('high CPU alone' in r for r in reasons), reasons)
        conditions['memory_pressure_evidence']['indicators'] = ['oom_kill', 'swap_activity']
        manifest, _ = freeze(conditions)
        self.assertEqual(manifest['session']['condition']['kind'], 'conditional')
        conditions['memory_pressure_evidence']['source_condition'] = 's-2vcpu-2gb-amd'
        self.assertTrue(any('source_condition must be s-1vcpu-1gb-amd' in r for r in rejection(conditions)))

    def test_primary_conditions_both_freeze(self):
        conditions = fx.conditions()
        conditions['roles']['game'].update(size_slug='s-2vcpu-2gb-amd', vcpus=2, memory_mib=2048, disk_gib=60)
        manifest, _ = freeze(conditions)
        self.assertEqual(manifest['session']['condition']['nominal_monthly_usd'], 21.0)

    def test_access_allowlists_and_metrics_privacy(self):
        conditions = fx.conditions()
        conditions['access_allowlists']['ssh_sources'] = ['0.0.0.0/0']
        self.assertTrue(any('world-open CIDR' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        conditions['access_allowlists']['metrics_public'] = True
        self.assertTrue(any('metrics stay private' in r for r in rejection(conditions)))

    def test_quota_project_and_timestamps(self):
        preflight = fx.preflight()
        preflight['account']['droplet_count'] = 24
        self.assertTrue(any('quota cannot hold both roles' in r for r in rejection(preflight=preflight)))
        preflight = fx.preflight()
        preflight['project']['id'] = 'other'
        self.assertTrue(any('omega.realm project' in r for r in rejection(preflight=preflight)))
        self.assertTrue(any('observed_at is after frozen_at' in r
                            for r in rejection(when='2026-10-30T11:00:00+00:00')))
        self.assertTrue(any('UTC offset' in r for r in rejection(when='2026-10-30T12:00:00')))

    def test_grace_plus_reserve_must_fit_inside_cap(self):
        conditions = fx.conditions()
        conditions['limits']['max_session_duration_s'] = 400
        self.assertTrue(any('leave no time inside the cap' in r for r in rejection(conditions)))

    def test_evidence_root_and_destination(self):
        conditions = fx.conditions()
        conditions['evidence']['local_root'] = 'somewhere/else'
        self.assertTrue(any('evidence.local_root must be' in r for r in rejection(conditions)))
        conditions = fx.conditions()
        del conditions['evidence']['durable_destination']
        self.assertTrue(any('durable_destination is required before a capacity session' in r
                            for r in rejection(conditions)))

    def test_all_reasons_are_reported_not_just_the_first(self):
        conditions = fx.conditions()
        del conditions['limits']['max_session_duration_s']
        conditions['source']['clean'] = False
        reasons = rejection(conditions)
        self.assertGreaterEqual(len(reasons), 2)


if __name__ == '__main__':
    unittest.main()
