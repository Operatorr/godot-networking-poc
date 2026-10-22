#!/usr/bin/env python3
"""Offline authoritative emission audit and exact-key legacy anomaly attribution."""
import collections
import csv
import hashlib
import json
import math
import pathlib
import struct
import aoi150 as controller

ROOT = pathlib.Path(__file__).resolve().parents[2]
PRIVATE = ROOT/'deployment/hetzner/results'/controller.NAMESPACE
PUBLIC = ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-22-aoi-diagnosis'


def f32(x):
    return struct.unpack('f', struct.pack('f', float(x)))[0]


def distance(center, entity):
    dx, dy = (f32(f32(b)-f32(a)) for a,b in zip(center,entity))
    return f32(math.sqrt(f32(f32(dx*dx)+f32(dy*dy))))


def correlate(anomaly, matches):
    if len(matches) != 1:
        return {'classification':'unknown-missing' if not matches else 'unknown-ambiguous', 'match_count':len(matches)}
    row = matches[0]
    d = distance((row['x'],row['y']), anomaly['entity_position'])
    compatible = d<=f32(row['max_distance']) and anomaly['baseline']==(row['baseline']=='true')
    return {'classification':'unknown-incompatible-witness' if not compatible else 'authoritative-violation' if d>1150 else 'legacy-mixed-time-false-positive',
            'match_count':1, 'authoritative_distance_f32':d,
            'authoritative_center':[float(row['x']),float(row['y'])],
            'emitted_snapshot_max_distance':float(row['max_distance']),
            'entity_within_emitted_max':d<=f32(row['max_distance']),
            'baseline_matches':anomaly['baseline']==(row['baseline']=='true')}


def analyze(directory, window):
    with (directory/'game/ticks.csv').open() as f:
        tick_rows=list(csv.DictReader(f))
    ticks={int(r['tick']):int(r['utc_ns']) for r in tick_rows}
    if len(ticks)!=len(tick_rows):raise ValueError('Ambiguous Tick timestamps')
    report=json.loads((directory/'bots/bot.json').read_text())
    bots=report['per_bot']
    anomalies=[dict(a,bot_id=b['bot_id']) for b in bots for a in b['aoi_anomalies']]
    key=lambda a:(int(a['observer_id']),int(a['snapshot_tick']),int(a['server_ms']))
    retained={key(a) for a in anomalies};matches=collections.defaultdict(list)
    groups={name:dict(rows=0,records=0,positions=0,baselines=0,deltas=0,full_requests=0,violations=0,max_distance=0.0) for name in ('lifetime','steady','outside_steady','unknown_tick')}
    seen=set();duplicates=0;per_tick=collections.defaultdict(collections.Counter)
    with (directory/'game/aoi.csv').open() as f:
        for r in csv.DictReader(f):
            tick=int(r['tick']); k=(int(r['observer']),tick,int(r['server_ms']))
            if k in seen:duplicates+=1
            seen.add(k)
            if k in retained:matches[k].append(r)
            stamp=ticks.get(tick)
            period='unknown_tick' if stamp is None else 'steady' if window['start']<=stamp<=window['end'] else 'outside_steady'
            kind='baselines' if r['baseline']=='true' else 'deltas'
            per_tick[tick][kind]+=1
            if int(r['positions'])>int(r['records']):raise ValueError('Invalid record counts')
            for name in ('lifetime',period):
                g=groups[name];g['rows']+=1;g[kind]+=1
                for field in ('records','positions'):g[field]+=int(r[field])
                g['full_requests']+=r['full_request']=='true'
                g['violations']+=float(r['max_distance'])>1150
                g['max_distance']=max(g['max_distance'],float(r['max_distance']))
    attributed=[]
    for a in anomalies:
        utc=ticks.get(a['snapshot_tick'])
        attributed.append(a|correlate(a,matches[key(a)])|{'tick_utc_ns':utc,'period':'unknown' if utc is None else 'steady' if window['start']<=utc<=window['end'] else 'outside_steady'})
    server=[json.loads(line) for line in (directory/'game/server.ndjson').read_text().splitlines()]
    # Each cumulative sample must match an exact per-Tick audit prefix (or an accounted partial final Tick).
    prefixes={(0,0):[]};c=collections.Counter()
    for tick in sorted(per_tick):
        c.update(per_tick[tick]);prefixes.setdefault((c['baselines'],c['deltas']),[]).append(tick)
    reconciliation=[]
    for sample in server:
        pair=(sample['baselines'],sample['deltas']);possible=prefixes.get(pair,[])
        expected=collections.Counter()
        for t,counts in per_tick.items():
            if t in ticks and ticks[t]<=sample['utc_ns']:expected.update(counts)
        time_exact=pair==(expected['baselines'],expected['deltas'])
        reconciliation.append({'utc_ns':sample['utc_ns'],'boundary':sample.get('boundary'),
            'baselines':pair[0],'deltas':pair[1],'exact_audit_prefix':pair in prefixes, 'timestamp_consistent':time_exact,
            'timestamp_expected_baselines':expected['baselines'],'timestamp_expected_deltas':expected['deltas'],
            'matched_last_emission_ticks':possible,
            'last_prefix_tick_utc_ns':ticks.get(possible[-1]) if possible else None})
    last=server[-1]
    tail={k:groups['lifetime'][k]-last[k] for k in ('baselines','deltas')}
    final_exact=all(v==0 for v in tail.values())
    strict=report.get('regression_assertions',report.get('assertions'))
    results={'namespace':controller.NAMESPACE,'threshold':1150,'window':window,
        'semantics':'Server rows describe pre-outbox constructed Snapshots; emitted baselines/deltas count successful enqueue. Delivery is separate. Tick UTC from ticks.csv defines steady membership. Bot aggregates/anomalies are lifetime.',
        'groups':groups,'duplicate_audit_keys':duplicates,'row_guard':2000000,
        'audit_guard_exhausted':groups['lifetime']['rows']>=2000000,
        'metric_reconciliation':{'samples':reconciliation,'all_samples_match_exact_tick_prefix':all(r['exact_audit_prefix'] and r['timestamp_consistent'] for r in reconciliation),
            'final_sample_utc_ns':last['utc_ns'],'final_sample_players':len(last['players']),
            'final_sample_send_errors':last['send_errors'],'audit_minus_final_metrics':tail,'final_totals_exact':final_exact,
            'record_count_limit':'No independent emitted-record metric; audit record and positional totals are retained. Snapshot coverage is reconciled separately by baseline/delta counts.'},
        'authoritative_emission_validated':final_exact and all(r['exact_audit_prefix'] and r['timestamp_consistent'] for r in reconciliation) and not last['send_errors'] and not duplicates and not groups['unknown_tick']['rows'] and 0<groups['lifetime']['rows']<2000000 and not groups['lifetime']['violations'],
        'bot_lifetime':{'count':len(bots),'matched_positions':sum(b['aoi_matched_positions'] for b in bots),
            'unknown_positions':sum(b['aoi_unknown_positions'] for b in bots),'max_matched_distance_rounded':max(b['max_observed_entity_distance'] for b in bots),
            'max_legacy_distance':max(b['legacy_max_observed_entity_distance'] for b in bots),
            'per_bot':[{k:b[k] for k in ('bot_id','aoi_matched_positions','aoi_unknown_positions','max_observed_entity_distance','legacy_max_observed_entity_distance')} for b in bots]},
        'delivered_record_coverage':{'reported_state_updates':sum(b.get('state_updates_received',0) for b in bots),
            'reported_baselines':sum(b.get('baselines_received',0) for b in bots),
            'reported_remote_positions':sum(b['aoi_matched_positions']+b['aoi_unknown_positions'] for b in bots),
            'audit_emitted_remote_positions':groups['lifetime']['positions'],
            'limits':'Aggregate delivered observations are not a per-record delivery census; omitted same-Snapshot centers remain unknown. No server per-record successful-send metric exists.'},
        'strict_assertions_unmodified':strict,'legacy_anomaly_count':len(attributed),
        'legacy_classifications':dict(collections.Counter(a['classification'] for a in attributed)),
        'all_retained_anomalies_uniquely_attributed':all(a['match_count']==1 and a['entity_within_emitted_max'] and a['baseline_matches'] and a['tick_utc_ns'] is not None for a in attributed),
        'legacy_anomalies':attributed}
    return results


def main():
    manifest=json.loads((PRIVATE/'manifest.json').read_text())
    result=analyze(PRIVATE/'extracted',manifest['window'])
    full_path=PRIVATE/'aoi150-full-correlation.json'
    full_path.write_text(json.dumps(result,indent=2)+'\n')
    public=dict(result)
    details=public.pop('legacy_anomalies')
    public['legacy_classifications_by_tick_period']={period:dict(collections.Counter(a['classification'] for a in details if a['period']==period)) for period in ('steady','outside_steady','unknown')}
    public['legacy_timing_counts']={'ramp_or_warmup':sum(a['tick_utc_ns'] is not None and a['tick_utc_ns']<result['window']['start'] for a in details), 'steady':sum(a['period']=='steady' for a in details), 'after_window':sum(a['tick_utc_ns'] is not None and a['tick_utc_ns']>result['window']['end'] for a in details)}
    public['maximum_legacy_anomaly']=max(details,key=lambda a:a['legacy_distance'],default=None)
    public['full_attribution_evidence']={'path':str(full_path.relative_to(ROOT)),'sha256':hashlib.sha256(full_path.read_bytes()).hexdigest(),'retained_anomalies':len(details)}
    reconciled=public['metric_reconciliation']=dict(public['metric_reconciliation'])
    samples=reconciled.pop('samples')
    reconciled['sample_count']=len(samples)
    reconciled['boundary_and_final_samples']=[r for r in samples if r['boundary']]+samples[-1:]
    reconciled['nonmatching_samples']=[r for r in samples if not (r['exact_audit_prefix'] and r['timestamp_consistent'])]
    (PUBLIC/'aoi150-correlation.json').write_text(json.dumps(public,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('authoritative_emission_validated','legacy_anomaly_count','legacy_classifications','all_retained_anomalies_uniquely_attributed')}))

if __name__=='__main__':main()
