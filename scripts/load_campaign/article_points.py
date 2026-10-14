"""Curate graph inputs before archiving; never touch historical evidence bundles."""
import json
import pathlib
import sys

BOT_FIELDS = ('id', 'phase', 'inputs', 'missed_schedules', 'baseline_reference_misses',
              'unknown_delta_entities', 'shoot_inputs', 'ability_inputs', 'snapshots',
              'baselines', 'confirms', 'rtt_ms', 'visible_entities', 'snapshot_age_s',
              'delta_age_s', 'confirm_age_s', 'input_gaps', 'snapshot_gaps',
              'decode_failures', 'send_failures', 'panics')


def curate(directory):
    directory = pathlib.Path(directory)
    for name in ('bots.ndjson', 'server.ndjson'):
        path = directory / name
        if not path.exists():
            continue
        temporary = path.with_suffix('.points')
        with path.open() as source, temporary.open('x') as target:
            for line in source:
                row = json.loads(line)
                if name == 'bots.ndjson':
                    row['bots'] = [{key: bot[key] for key in BOT_FIELDS} for bot in row['bots']]
                else:
                    row.pop('event_sends', None)
                    row['players'] = [player[:2] for player in row['players']]
                target.write(json.dumps(row, separators=(',', ':')) + '\n')
        temporary.replace(path)
    log = directory / 'bot.log'
    if log.exists():
        # Progress/join lines do not support a graph or conclusion. Keep bounded diagnostics.
        lines = log.read_text().splitlines()
        diagnostics = [line for line in lines if 'WARN' in line or 'ERROR' in line]
        log.write_text('\n'.join((diagnostics[:20] + lines[-20:])) + '\n')
    (directory / 'collection-policy.json').write_text(json.dumps({
        'format': 'article-points-v1',
        'tick_points': 'Every Tick numeric work/population/backlog fields; exact percentile and player-second integrals.',
        'host_points': '1 Hz CPU/process/interface/UDP/qdisc/flow metrics and matched boundaries; no socket tables or full proc dumps.',
        'bot_points': '1 Hz cadence, RTT, delivery ages and error counters plus per-bot matched boundaries; no packet/event log.',
        'flow_points': 'Exact common-window bytes/packets/inputs/retries and 1 Hz traffic points from all packets.',
        'delivery_sample': '1/64 deterministic UDP fingerprint sample; no payload, headers or command descriptors. Estimates are conditional on the fingerprint sample, not exact all-packet loss.',
        'diagnostics': 'At most first 20 warning/error lines plus last 20 bot log lines.',
    }, indent=2) + '\n')


if __name__ == '__main__':
    curate(sys.argv[1])
