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
    missing, invalid = [], []
    expected = []
    def require(name):
        selected = replacements.get(name, {}).get('selected_run_id', name)
        expected.append(selected)
        path = run.RAW / selected / 'steady.json'
        if not path.exists():
            missing.append(selected)
            return None
        row = json.loads(path.read_text())
        if row.get('window_s') != 300 or not row.get('collector_valid'):
            invalid.append(selected)
        return row
    if state.get('core_complete'):
        for behavior in campaign.BEHAVIORS:
            failure = state.get('first_failed', {}).get(behavior, {}).get('population')
            for count in campaign.POPULATIONS:
                for repeat in range(1, 4):
                    require(f'core-{behavior}-{count}-r{repeat}')
                if count == failure:
                    break
            boundary = state.get('boundaries', {}).get(behavior)
            if boundary:
                if boundary['upper'] - boundary['lower'] > 25:
                    invalid.append(behavior + ': boundary wider than 25 players')
                for count in (boundary['lower'], boundary['upper']):
                    if count and count not in campaign.POPULATIONS:
                        for repeat in range(1, 4):
                            require(f'boundary-{behavior}-{count}-r{repeat}')
        for count in sorted({100, max(state['highest_stable'].values(), default=100)}):
            for repeat in range(1, 4):
                require(f'idle-{count}-r{repeat}')
        for behavior in ('combat', 'strategy'):
            highest = state['highest_stable'].get(behavior, 0)
            populations = ({100, highest} - {0}) if highest >= 100 else ({highest} - {0})
            for count in sorted(populations):
                for repeat in range(1, 4):
                    for position in ('before', 'after'):
                        require(f'network-control-{position}-{behavior}-{count}-r{repeat}')
                    for profile in netem.PROFILES:
                        require(f'network-{behavior}-{count}-{profile}-r{repeat}')
        common = min(state['highest_stable'].get(behavior, 0) for behavior in ('combat', 'clustered', 'strategy'))
        for behavior in ('combat', 'clustered', 'strategy'):
            for count in sorted({100, common} - {0}):
                for repeat in range(1, 4):
                    variants = ['native', 'aoi600', 'snapshot15', 'native'] if repeat == 2 else ['native', 'snapshot15', 'aoi600', 'native']
                    for index, variant in enumerate(variants):
                        require(f'transfer-{behavior}-{count}-{variant}-{index}-r{repeat}')
    external = require('external-combat-3-r1')
    admission_required = state.get('highest_stable', {}).get('movement') == 999
    admission_path = run.RAW / 'admission-resolution.json'
    admission_complete = not admission_required or (admission_path.exists() and json.loads(admission_path.read_text()).get('passed'))
    complete = (all(state.get(flag) for flag in ('core_complete', 'network_complete', 'transfer_complete'))
                and not missing and not invalid and admission_complete
                and external and external['classification'] == 'external-accounting-check-valid')
    result = {'complete': bool(complete), 'phase_flags': state, 'expected_cell_count': len(expected),
              'missing_cells': missing, 'invalid_collection_cells': invalid,
              'admission_required': admission_required, 'admission_complete': admission_complete,
              'note': 'Coverage allows retained valid failures and generator-invalid cells; they cannot establish sustainable server capacity.'}
    (publish.OUTPUT / 'matrix-coverage.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    result = verify()
    print(json.dumps({'complete': result['complete'], 'expected_cells': result['expected_cell_count'],
                      'missing': len(result['missing_cells']), 'invalid_collection': len(result['invalid_collection_cells'])}))
