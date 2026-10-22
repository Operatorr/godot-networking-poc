#!/usr/bin/env python3
"""Offline native retirement/socket/capture reconciliation on real isolated extraction.

Retains exact clock-window differences. Handoff != network arrival != application delivery.
Raw input records contain numeric metadata/fingerprint only, never payload or Debug text.
"""
import collections
import csv
import hashlib
import json
import pathlib
import struct

RECORD=struct.Struct('<QQQQQIIIIII')
DATAGRAM=struct.Struct('<QHHHHQH')
ERRORS=('trace_limit','pending_limit','write_errors','untracked_retirement','whitelist_errors',
        'parser_errors','duplicate_input_attempt','unmatched_socket_input','socket_zero',
        'socket_partial','socket_errors','receive_errors','receive_partial','service_errors')

def read_records(path):
    data=path.read_bytes()
    if len(data)%RECORD.size or len(data)>16384*64:raise ValueError('Native trace truncated/oversized')
    return list(RECORD.iter_unpack(data))

def capture_inputs(path, known):
    result=collections.Counter()
    with path.open('rb') as stream:
        if stream.read(4)!=b'ORF1':raise ValueError('Capture magic')
        while raw:=stream.read(DATAGRAM.size):
            if len(raw)!=DATAGRAM.size:raise ValueError('Capture record truncation')
            stamp,source,target,ip_len,udp_len,fingerprint,commands=DATAGRAM.unpack(raw)
            if commands:raise ValueError('Expected compact v2 capture')
            key=(source,fingerprint)
            if target==8081 and key in known:result[key]+=1
    return result

def analyze(directory, manifest):
    d=pathlib.Path(directory)
    if any(p.is_symlink() or (p.is_file() and p.stat().st_nlink!=1) for p in d.rglob('*')):
        raise ValueError('Analysis requires real isolated copies')
    observations=[json.loads(line) for line in (d/'bots/bots.ndjson').read_text().splitlines()]
    final={b['id']:b['native_diagnostic'] for b in observations[-1]['bots']}
    mappings={}
    for role in ('game','bots'):
        with (d/role/'port-bot.csv').open() as stream:
            mappings[role]={int(r['bot_id']):int(r['port']) for r in csv.DictReader(stream)}
    population=manifest['requested_bots']; start,end=(manifest['window'][k] for k in ('start','end'))
    checks={'identity_map_complete':mappings['game']==mappings['bots'] and set(mappings['bots'])==set(range(1,population+1)),
            'final_diagnostic_complete':set(final)==set(range(1,population+1)) and all(isinstance(v,dict) and v.get('schema')==1 for v in final.values())}
    if not all(checks.values()):return dict(checks=checks,evidence_complete=False)
    peers=[];fingerprints=collections.Counter();cost=0;errors=collections.Counter();total=collections.Counter()
    evidence={}
    for i,diag in sorted(final.items()):
        path=d/'bots'/f'native-{i}.bin';records=read_records(path);c=diag['counts'];counts=collections.Counter(r[9] for r in records)
        native=[r for r in records if r[9]==1]
        window=[r for r in native if start<=r[2]<end]
        for r in native:
            if r[4]%64==0:fingerprints[mappings['bots'][i],r[4]]+=1
        error={k:c.get(k,0) for k in ERRORS};errors.update(error);cost+=diag['completed_observer_ns']
        full=dict(admitted=c.get('admitted',0),retired=len(records),socket_input_handoffs=len(native),
            no_attempt=counts[5],zero=counts[2],partial=counts[3],error=counts[4],pending=diag['pending_inputs'],
            throttle_witness=c.get('no_attempt_single_step_throttle_witness',0),unclassified=c.get('no_attempt_unclassified',0))
        interval=dict(admitted=sum(start<=r[0]<end for r in records),handoffs=len(window),
            no_attempt_admissions=sum(start<=r[0]<end and r[9]==5 for r in records),
            carried_in=sum(r[0]<start and start<=r[2]<end for r in native),
            carried_out=sum(start<=r[0]<end and r[2]>=end for r in native),
            pending_at_start=sum(r[0]<start<=r[1] for r in records),pending_at_end=sum(r[0]<end<=r[1] for r in records))
        expected=interval['no_attempt_admissions']+interval['carried_out']-interval['carried_in']
        # This identity accounts for admission-to-socket differences within one clock domain.
        accounting=(interval['admitted']-interval['handoffs']==expected and full['pending']==0 and
            full['admitted']==len(records)==c.get('retired',0) and full['socket_input_handoffs']==c.get('socket_input_handoffs',0) and
            full['throttle_witness']+full['unclassified']==full['no_attempt'] and
            all(r[3]==n for n,r in enumerate(records,1)) and diag['trace_records']==len(records))
        throttle_raw=sum(r[9]==5 and r[5]<=32 and r[6]<32 and r[8]==(r[6]+7)%32 and r[8]>r[5] for r in records)
        cap={role:json.loads((d/role/'flow-summary.json').read_text())['wire_input_counts_by_port'].get(str(mappings[role][i]),0) for role in ('game','bots')}
        peer=dict(id=i,full=full,window=interval,capture_window=cap,
            native_minus_capture={role:len(window)-n for role,n in cap.items()},
            native_attempts_within_10ms_of_boundary=sum(any(abs(r[2]-t)<=10_000_000 for t in (start,end)) for r in native),
            throttle_min=diag['throttle_min'],raw_single_counter_witnesses=throttle_raw,
            max_retirement_age_ns=diag['max_input_retirement_age_ns'],max_service_gap_ns=diag['max_service_gap_ns'],
            max_service_bracket_ns=diag['max_service_bracket_ns'],last_numeric_peer=diag['last_numeric_peer'],
            accounting=accounting,trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),trace_bytes=path.stat().st_size)
        peers.append(peer);total.update(full)
    capture={role:capture_inputs(d/role/'datagrams.bin',fingerprints) for role in ('game','bots')}
    matched={role:dict(native_sampled_input_datagrams=sum(fingerprints.values()),capture_matched=sum(capture[role].values()),
        missing=sum((fingerprints-capture[role]).values()),extra=sum((capture[role]-fingerprints).values())) for role in capture}
    checks.update(all_native_accounting=all(p['accounting'] for p in peers),all_observer_and_socket_error_counters_zero=not any(errors.values()),
        all_no_attempts_have_single_step_throttle_witness=total['no_attempt']==total['throttle_witness'] and total['unclassified']==0 and all(p['raw_single_counter_witnesses']==p['full']['no_attempt'] for p in peers),
        sampled_fingerprints_match_both_captures=all(v['missing']==v['extra']==0 for v in matched.values()),
        capture_count_differences_bounded_by_boundary_candidates=all(abs(delta)<=p['native_attempts_within_10ms_of_boundary'] for p in peers for delta in p['native_minus_capture'].values()))
    return dict(schema=1,checks=checks,evidence_complete=all(checks.values()),full=dict(total),errors=dict(errors),peers=peers,
        sampled_fingerprint_reconciliation=matched,completed_observer_ns=cost,
        record_bytes=sum(p['trace_bytes'] for p in peers),
        semantics='Native attempts timestamped immediately before unchanged Socket::send; successful full-length returns are socket handoffs. Native/capture windows use different clock sources and capture timestamps have microsecond resolution. Whole-run sampled full-UDP fingerprints are matched independently of the collector command parser. Exact application delivery remains unknown. Pending input-buffer lifecycle is measured; native queue lengths and reliable queue occupancy remain unknown. Instrumentation cost is measured internally and may alter overhead; no historical causal attribution follows.')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=pathlib.Path);parser.add_argument('manifest',type=pathlib.Path);parser.add_argument('output',type=pathlib.Path)
    args=parser.parse_args();result=analyze(args.directory,json.loads(args.manifest.read_text()))
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps({k:result[k] for k in ('checks','evidence_complete','full')}))
