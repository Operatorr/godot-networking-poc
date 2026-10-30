#!/usr/bin/env python3
"""Offline planning/preflight CLI for a DigitalOcean test session (handoff slice 1).

    do_session.py freeze   --conditions c.json --preflight p.json --session-root loadtest-runs/digitalocean --now ISO
    do_session.py admit    --session-dir DIR --now ISO --infra-health h.json [--resume]
    do_session.py next-run --session-dir DIR --now ISO --infra-health h.json [--resume]
    do_session.py record   --session-dir DIR --run-id ID --outcome PASS|FAIL|... [--evidence-ref REF] --now ISO
    do_session.py mark-t0  --session-dir DIR --now ISO
    do_session.py stop     --session-dir DIR --reason time_exhausted --now ISO
    do_session.py paths    --session-dir DIR

Exit codes: 0 admitted/done, 2 rejected, 3 no remaining work. Nothing here talks to a
provider, SSH or the network; the session directory is the only side effect, and every
write is create-only or append-only.
"""
import argparse
import json
import pathlib
import sys

import admission
import manifest as manifest_mod
import search

JOURNAL = 'search_journal.ndjson'


def load_json(path):
    return json.loads(pathlib.Path(path).read_text())


def write_new(path, text):
    """Create-only write: an existing file is immutable evidence and is never overwritten."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(text)


def append_journal(session_dir, record):
    with (pathlib.Path(session_dir) / JOURNAL).open('a', encoding='utf-8') as handle:
        handle.write(manifest_mod.canonical_json(record))


def load_session(session_dir):
    """Return (manifest, sha256, state, journal_meta) after verifying the manifest hash."""
    session_dir = pathlib.Path(session_dir)
    manifest = load_json(session_dir / 'manifest.json')
    sha = (session_dir / 'manifest.sha256').read_text().split()[0]
    manifest_mod.verify_manifest(manifest, sha)
    condition_id = manifest['session']['id']
    state = search.SearchState(condition_id)
    meta = dict(t0=None, phase='pre_create', manifest_sha256=sha)
    journal = session_dir / JOURNAL
    if journal.exists():
        for line in journal.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get('manifest_sha256') not in (None, sha):
                raise manifest_mod.ManifestError(['journal entry was written against manifest '
                                                  + str(entry.get('manifest_sha256')) + ', not ' + sha])
            kind = entry['kind']
            if kind == 'selected':
                trial = search.Trial(**{k: (tuple(v) if k == 'predecessors' else v)
                                        for k, v in entry['trial'].items()
                                        if k in search.Trial.__dataclass_fields__})
                state = state.with_record(search.TrialRecord(trial))
            elif kind == 'outcome':
                state = search.record_outcome(state, entry['run_id'], entry['outcome'], entry.get('evidence_ref'))
            elif kind == 't0':
                meta['t0'] = entry['t0_utc']
                meta['phase'] = 'pair_ready'
            elif kind == 'stop':
                state.stop_reason = entry['reason']
    return manifest, sha, state, meta


def cmd_freeze(args):
    conditions = load_json(args.conditions)
    preflight = load_json(args.preflight)
    try:
        manifest, sha = manifest_mod.freeze_manifest(conditions, preflight, args.now)
    except manifest_mod.ManifestError as error:
        print(json.dumps(dict(frozen=False, reasons=error.reasons), indent=2))
        return 2
    session_dir = pathlib.Path(args.session_root) / manifest['session']['id']
    write_new(session_dir / 'manifest.json', manifest_mod.canonical_json(manifest))
    write_new(session_dir / 'manifest.sha256', sha + '  manifest.json\n')
    print(json.dumps(dict(frozen=True, session_dir=str(session_dir), manifest_sha256=sha,
                          condition=manifest['session']['condition']['name']), indent=2))
    return 0


def evaluate(args, resume):
    manifest, sha, state, meta = load_session(args.session_dir)
    health = load_json(args.infra_health) if args.infra_health else None
    return manifest, sha, state, meta, admission.admit(
        manifest, sha, state, args.now, health, phase=meta['phase'], t0=meta['t0'],
        resume_requested=resume, current_limits=load_json(args.limits) if args.limits else None)


def persist_admission(session_dir, result, kind):
    stamp = result.evaluated_at.replace(':', '').replace('+0000', 'Z')
    path = pathlib.Path(session_dir) / 'admissions' / (stamp + '-' + kind + '.json')
    suffix = 0
    while path.exists():
        suffix += 1
        path = path.with_name(stamp + '-' + kind + '-' + str(suffix) + '.json')
    write_new(path, json.dumps(result.to_dict(), indent=2, sort_keys=True) + '\n')
    return path


def exit_code(result):
    return {admission.ADMITTED: 0, admission.NO_REMAINING_WORK: 3}.get(result.decision, 2)


def cmd_admit(args):
    _, _, _, _, result = evaluate(args, args.resume)
    persist_admission(args.session_dir, result, 'resume' if args.resume else 'admit')
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return exit_code(result)


def cmd_next_run(args):
    manifest, sha, state, meta, result = evaluate(args, args.resume)
    persist_admission(args.session_dir, result, 'dispatch')
    if not result.admitted:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return exit_code(result)
    trial = search.next_trial(state)
    record = dict(kind='selected', manifest_sha256=sha, selected_at=result.evaluated_at,
                  trial=trial.to_dict(), predecessor_evidence=[
                      dict(run_id=r.trial.run_id, outcome=r.outcome, evidence_ref=r.evidence_ref)
                      for r in state.records if r.trial.run_id in trial.predecessors],
                  admission_decision=result.decision, resume=args.resume)
    # Materialize the concrete run durably BEFORE any dispatch could happen (create-only).
    write_new(pathlib.Path(args.session_dir) / 'runs' / trial.run_id / 'selected.json',
              json.dumps(record, indent=2, sort_keys=True) + '\n')
    append_journal(args.session_dir, record)
    print(json.dumps(dict(result.to_dict(), selected=record), indent=2, sort_keys=True))
    return 0


def cmd_record(args):
    manifest, sha, state, _ = load_session(args.session_dir)
    state = search.record_outcome(state, args.run_id, args.outcome, args.evidence_ref)
    append_journal(args.session_dir, dict(kind='outcome', manifest_sha256=sha, run_id=args.run_id,
                                          outcome=args.outcome, evidence_ref=args.evidence_ref,
                                          recorded_at=admission.parse_utc(args.now).isoformat()))
    derived = search.derive(state)
    print(json.dumps(dict(status=derived['status'], detail=derived['detail'], candidate=derived['candidate'],
                          counts=derived['counts'], result=derived['result']), indent=2, sort_keys=True))
    return 0


def cmd_mark_t0(args):
    _, sha, _, meta = load_session(args.session_dir)
    if meta['t0'] is not None:
        print(json.dumps(dict(error='t0 already recorded at ' + meta['t0'] + '; the deadline is immutable')))
        return 2
    append_journal(args.session_dir, dict(kind='t0', manifest_sha256=sha,
                                          t0_utc=admission.parse_utc(args.now).isoformat()))
    print(json.dumps(dict(t0_utc=admission.parse_utc(args.now).isoformat())))
    return 0


def cmd_stop(args):
    _, sha, _, _ = load_session(args.session_dir)
    append_journal(args.session_dir, dict(kind='stop', manifest_sha256=sha, reason=args.reason,
                                          stopped_at=admission.parse_utc(args.now).isoformat()))
    print(json.dumps(dict(stopped=True, reason=args.reason)))
    return 0


def cmd_paths(args):
    manifest, _, state, _ = load_session(args.session_dir)
    paths = search.legal_paths(state)
    summaries = [search.path_summary(p) for p in paths]
    longest = max(summaries, key=lambda s: s['scored_hold_s'])
    print(json.dumps(dict(legal_remaining_paths=len(paths),
                          max_trials=max(s['trials'] for s in summaries),
                          max_scored_hold_min=longest['scored_hold_min'],
                          longest_hold_path=longest), indent=2, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    freeze = sub.add_parser('freeze')
    freeze.add_argument('--conditions', required=True)
    freeze.add_argument('--preflight', required=True)
    freeze.add_argument('--session-root', default='loadtest-runs/digitalocean')
    freeze.add_argument('--now', required=True, help='controller UTC time, ISO-8601 with offset')
    freeze.set_defaults(func=cmd_freeze)

    for name, func in (('admit', cmd_admit), ('next-run', cmd_next_run)):
        command = sub.add_parser(name)
        command.add_argument('--session-dir', required=True)
        command.add_argument('--now', required=True)
        command.add_argument('--infra-health', required=True, help='registry/watchdog health JSON')
        command.add_argument('--limits', help='limits currently in force, to prove they are unchanged')
        command.add_argument('--resume', action='store_true', help='explicit operator resume request')
        command.set_defaults(func=func)

    record = sub.add_parser('record')
    record.add_argument('--session-dir', required=True)
    record.add_argument('--run-id', required=True)
    record.add_argument('--outcome', required=True, choices=search.OUTCOMES)
    record.add_argument('--evidence-ref')
    record.add_argument('--now', required=True)
    record.set_defaults(func=cmd_record)

    for name, func in (('mark-t0', cmd_mark_t0), ('stop', cmd_stop)):
        command = sub.add_parser(name)
        command.add_argument('--session-dir', required=True)
        command.add_argument('--now', required=True)
        if name == 'stop':
            command.add_argument('--reason', required=True,
                                 choices=('time_exhausted', 'spend_exhausted', 'operator_stop'))
        command.set_defaults(func=func)

    paths = sub.add_parser('paths')
    paths.add_argument('--session-dir', required=True)
    paths.set_defaults(func=cmd_paths)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (manifest_mod.ManifestError, search.SearchError, FileExistsError, ValueError) as error:
        print(json.dumps(dict(error=str(error))), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
