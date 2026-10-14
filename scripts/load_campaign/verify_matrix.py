#!/usr/bin/env python3
"""Independently verify matrix coverage before resolving the execution ticket."""
import json
import run
import campaign
import netem
import publish


def verify():
    state = json.loads(campaign.STATE.read_text()) if campaign.STATE.exists() else {}
    replacement_path = run.RAW / 'matrix-replacements.json'
    replacements = json.loads(replacement_path.read_text()) if replacement_path.exists() else {}
    missing, invalid, inconsistent = [], [], []
    expected = []
    rows = {}
    def require(name):
        selected = replacements.get(name, {}).get('selected_run_id', name)
        expected.append(selected)
        path = run.RAW / selected / 'steady.json'
        if not path.exists():
            missing.append(selected)
            return None
        row = json.loads(path.read_text())
        rows[selected] = row
        if row.get('requested_bots', 0) >= 200 and row.get('behavior') != 'strategy':
            inconsistent.append(selected + ': only Strategy is allowed at 200 or more players')
        if row.get('window_s') != 300 or not row.get('collector_valid'):
            invalid.append(selected)
        if row.get('run_id') != selected:
            inconsistent.append(selected + ': result identity mismatch')
        if not row.get('ended_utc'):
            inconsistent.append(selected + ': missing ended manifest')
        if row.get('classification') == 'native-stable-candidate' and not (
            row.get('generator_valid') and row.get('server_sustainability_gate')
            and row.get('server_send_errors') == 0 and row.get('server_decode_errors') == 0
            and not row.get('game_kernel_udp_errors') and not row.get('bots_kernel_udp_errors')
        ):
            inconsistent.append(selected + ': native pass contradicts measured validity/errors')
        archives = row.get('archive_sha256', {})
        for role in ('game', 'bots'):
            archive = role + '.tar.gz'
            if not (path.parent / archive).is_file() or len(archives.get(archive, '')) != 64:
                inconsistent.append(selected + ': retained archive absent or checksum missing: ' + archive)
        config = row.get('game_config', {})
        variant = row.get('variant', 'native')
        expected_config = {'mode': 'arena', 'tick_rate': 30, 'max_players': 999,
                           'api_server_url': '', 'allow_unsigned_tickets': True,
                           'default_client_bandwidth_bps': 120000, 'max_client_bandwidth_bps': 200000,
                           'monster_ai_difficulty': 0.85,
                           'snapshot_rate_hz': 15 if variant == 'snapshot15' else 30,
                           'aoi_radius': 600 if variant == 'aoi600' else 1000,
                           'aoi_exit_radius': 660 if variant == 'aoi600' else 1100,
                           'lod_near_radius': 400, 'lod_mid_radius': 600 if variant == 'aoi600' else 1000}
        for key, value in expected_config.items():
            if config.get(key) != value:
                inconsistent.append(selected + ': resolved setting mismatch: ' + key)
        return row
    def group(prefix):
        return [require(f'{prefix}-r{repeat}') for repeat in campaign.REPETITIONS]
    def stable(group_rows):
        return all(row and row['classification'] == 'native-stable-candidate' for row in group_rows)
    # Even an unfinished campaign must expose its initial pending cells instead of
    # making the already-finished external check appear to be the whole matrix.
    if not state.get('core_complete'):
        for behavior in campaign.BEHAVIORS:
            group(f'core-{behavior}-50')
    if state.get('core_complete'):
        for behavior in campaign.BEHAVIORS:
            planned_populations = campaign.populations_for_workload(behavior)
            failure = state.get('first_failed', {}).get(behavior, {}).get('population')
            if failure is not None and failure not in planned_populations:
                inconsistent.append(behavior + ': failed ladder rung is outside the matrix')
            for count in planned_populations:
                observed = group(f'core-{behavior}-{count}')
                if all(observed) and stable(observed) == (count == failure):
                    inconsistent.append(f'{behavior}-{count}: ladder classification contradicts declared first failure')
                if count == failure:
                    break
            boundary = state.get('boundaries', {}).get(behavior)
            if failure and not boundary:
                inconsistent.append(behavior + ': failed ladder lacks boundary refinement')
            if boundary:
                if boundary['upper'] - boundary['lower'] > 25:
                    invalid.append(behavior + ': boundary wider than 25 players')
                for count in (boundary['lower'], boundary['upper']):
                    if count:
                        prefix = 'core' if count in planned_populations else 'boundary'
                        observed = group(f'{prefix}-{behavior}-{count}')
                        if all(observed) and stable(observed) != (count == boundary['lower']):
                            inconsistent.append(f'{behavior}-{count}: boundary side classification mismatch')
                if state['highest_stable'].get(behavior, 0) != boundary['lower']:
                    inconsistent.append(behavior + ': highest stable population differs from verified boundary')
            elif not failure and state['highest_stable'].get(behavior) != planned_populations[-1]:
                inconsistent.append(behavior + ': untruncated ladder must reach its planned population limit')
        for count in campaign.idle_populations(state['highest_stable']):
            for repeat in campaign.REPETITIONS:
                require(f'idle-{count}-r{repeat}')
        for behavior in ('combat', 'strategy'):
            highest = state['highest_stable'].get(behavior, 0)
            populations = ({100, highest} - {0}) if highest >= 100 else ({highest} - {0})
            for count in sorted(populations):
                for repeat in campaign.REPETITIONS:
                    for position in ('before', 'after'):
                        control = require(f'network-control-{position}-{behavior}-{count}-r{repeat}')
                        if control and not stable([control]):
                            inconsistent.append(control['run_id'] + ': impairment bracket lacks a passing native control')
                    for profile in netem.PROFILES:
                        require(f'network-{behavior}-{count}-{profile}-r{repeat}')
        common = min(state['highest_stable'].get(behavior, 0) for behavior in ('combat', 'clustered', 'strategy'))
        for behavior in ('combat', 'clustered', 'strategy'):
            for count in sorted({100, common} - {0}):
                for repeat in campaign.REPETITIONS:
                    variants = ['native', 'snapshot15', 'aoi600', 'native']
                    for index, variant in enumerate(variants):
                        require(f'transfer-{behavior}-{count}-{variant}-{index}-r{repeat}')
    external = require('external-combat-3-r1')
    admission_required = state.get('highest_stable', {}).get('strategy') == 999
    admission_path = run.RAW / 'admission-resolution.json'
    admission_complete = not admission_required or (admission_path.exists() and json.loads(admission_path.read_text()).get('passed'))
    complete = (all(state.get(flag) for flag in ('core_complete', 'network_complete', 'transfer_complete'))
                and not missing and not invalid and not inconsistent and admission_complete
                and external and external['classification'] == 'external-accounting-check-valid')
    result = {'complete': bool(complete), 'required_runs_per_condition': len(campaign.REPETITIONS), 'phase_flags': state, 'expected_cell_count': len(set(expected)),
              'missing_cells': sorted(set(missing)), 'invalid_collection_cells': sorted(set(invalid)),
              'inconsistent_evidence': sorted(set(inconsistent)), 'recorded_expected_cells': len(rows),
              'admission_required': admission_required, 'admission_complete': admission_complete,
              'note': 'Coverage allows retained valid failures and generator-invalid cells; they cannot establish sustainable server capacity.'}
    (publish.OUTPUT / 'matrix-coverage.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    result = verify()
    print(json.dumps({'complete': result['complete'], 'expected_cells': result['expected_cell_count'],
                      'missing': len(result['missing_cells']), 'invalid_collection': len(result['invalid_collection_cells']),
                      'inconsistent': len(result['inconsistent_evidence'])}))
