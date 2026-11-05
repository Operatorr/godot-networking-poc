#!/usr/bin/env python3
"""The verified inventory of one DigitalOcean session, and its reports (handoff slice 7, issue #70).

    session_export.py export          --session-dir D [--registry-command C]   a new generation, with the registry's word on cleanup when it can be read
    session_export.py verify          --session-dir D [--generation G]         every recorded hash against the disk
    session_export.py reproduce       --session-dir D [--generation G]         every report again from the same retained inputs, byte for byte
    session_export.py prepare-publication  --session-dir D [--generation G] --now T [--docs-root R] [--repository P]   the text only, past the guard, into the repository's docs directory on this machine. That is placement, not publication
    session_export.py record-publication   --session-dir D --generation G --reference U --summary-sha256 S --operator O --now T   what the operator committed and pushed, in their name and at its commit
    session_export.py record-journal  --session-dir D --generation G --url U --summary-sha256 S --now T           what the operator mirrored by hand
    session_export.py record-invoice  --session-dir D --period P --amount-usd A --source S --now T                a later provider charge, kept apart from every estimate

Layout, under ``loadtest-runs/digitalocean/<session_id>/``: the immutable manifest and hash, ``search_journal.ndjson``, ``admissions/``, ``provisioning/`` and ``execution/`` journals, then ``runs/<run_id>/`` with separate ``game/`` and ``bot/`` trees, window proof, score, classification, ``summary.json`` and ``REPORT.md``,
and ``export/gen-NNNN/`` for each export. A generation is written whole under another name and renamed into place, so a crash or a full disk leaves a ``.writing`` directory and no generation. Nothing is ever replaced: a later export is a later generation, and a fact it learned does not unsay an earlier one.

    export/gen-NNNN/inventory.json     statuses and every file's hash
    export/gen-NNNN/SHA256SUMS         the same hashes, in the form the raw evidence can be checked against
    export/gen-NNNN/inputs/            what the registry said and what the search said, so the reports below need no live answer
    export/gen-NNNN/journals/          the exact bytes of each append-only journal as hashed here, since the journal itself goes on growing
    export/gen-NNNN/session-report.json, REPORT.md    the private reports
    export/gen-NNNN/published/         the only text that may leave the laptop. Absent when the guard refused it

Evidence is ``complete`` only when every role the durable records say was meant for a host has a seal that holds up, every file it lists verified, and every file its plan and the frozen schema require among them, with the controller's own inputs for each run, what readiness pinned by hash and the session's own records present, and when every path under the session could be listed and read. Anything else says what it is:
``corrupt`` over ``missing`` over ``partial``. Each is independent of what was measured and of whether the resources are gone. This module deletes nothing, extends nothing and holds nothing up: cleanup is requested whatever happens here, and the watchdog deletes by C regardless.

Pure over retained files, except that ``export`` asks a registry for its status when given one. Runs with no provider, SSH or network access of its own, and the checkout it runs from decides nothing.
"""
import argparse
import dataclasses
import json
import math
import os
import pathlib
import shlex
import stat
import sys
import tempfile

import admission
import capacity_report
import capacity_scorer
import cleanup_provider
import do_session
import evidence_publication
import guest_runner
import manifest as manifest_mod
import measurement_window as mw
import registry_client
import run_plan
import session_report

INVENTORY_SCHEMA = 'omega.do-session.evidence-inventory/2'
INVOICE_SCHEMA = 'omega.do-session.invoice-fact/1'
EXPORT_DIR = 'export'
GENERATION_NAME = 'gen-%04d'
SUMS_FILE = 'SHA256SUMS'
INVENTORY_FILE = 'inventory.json'
REPORT_JSON = 'session-report.json'
REPORT_MD = 'REPORT.md'
INVOICE_DIR = 'invoices'
INPUTS = 'inputs'
JOURNALS = 'journals'
PUBLISHED = 'published'
ANY_TOKEN = 2 ** 62     # offline, no fence is being enforced: every receipt is old enough to count
APPEND_ONLY = frozenset((do_session.JOURNAL, 'provisioning/journal.ndjson', 'execution/journal.ndjson'))
PARTIAL_MARK = '.partial'
ROLES = ('game', 'bot')
RECORDER_DOCUMENTS = dict(game='telemetry/process.json', bot='swarm/swarm.json')
READ_FAILURES = (OSError, ValueError, KeyError, TypeError, RecursionError)
# In this order a worse word wins.
STATUS_ORDER = ('corrupt', 'missing', 'partial', 'complete')


def sha256_path(path):
    return guest_runner.sha256_file(path)


def _read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError, RecursionError):
        return None


# ---- what one role left --------------------------------------------------------------------------------

def _partial_attempts(path):
    """A file's retained attempts: the current ``.partial`` and each earlier one set aside. A later transfer never overwrites an earlier one."""
    try:
        return sorted(item for item in path.parent.iterdir() if item.name == path.name + PARTIAL_MARK or item.name.startswith(path.name + PARTIAL_MARK + '.'))
    except OSError:
        return []


def file_status(path, digest):
    """A retained ``.partial`` is never promoted, so with only that a file is not verified. Bad bytes say corrupt, and no bytes say missing."""
    try:
        if path.exists():
            return 'verified' if sha256_path(path) == digest else 'corrupt'
        return 'corrupt' if any(sha256_path(item) != digest for item in _partial_attempts(path)) else 'missing'
    except OSError:
        return 'unreadable'


def _required_files(plan, role, manifest):
    """What this role has to have left: its plan's list, and the pinned measurement schema's when the session froze that schema. A manifest's free-form list predates that schema and does not outrank it."""
    required = set(plan.get('required_on_clean_exit') or ()) if isinstance(plan, dict) else set()
    frozen = (manifest or {}).get('telemetry_schema') or {}
    if frozen.get('id') == mw.schema()['id'] and frozen.get('sha256') == mw.schema_sha256():
        threads = ((manifest or {}).get('workload') or {}).get('generator_threads')
        for name in mw.schema()['files'].get(role) or ():
            name = name.split(' ')[0]
            if '<k>' in name:
                if isinstance(threads, int):
                    required.update(name.replace('<k>', str(index)) for index in range(threads))
            else:
                required.add(name)
    return sorted(required)


def role_inventory(run_dir, run_id, role, session_id=None, manifest_sha256=None, manifest=None, token=ANY_TOKEN):
    """One role's files as they are on this disk, each held to the seal, and the seal held to what is already on record for this run.

    ``status`` answers whether a further transfer could help, so ``verified`` means the seal stands and every file it lists is here with the bytes it says. ``required_absent`` and ``problems`` are what still keeps that role from being complete evidence, and they are for the session's status.
    """
    run_dir = pathlib.Path(run_dir)
    target = run_dir / role
    plan = _read_json(run_dir / ('plan-%s.json' % role))
    required = _required_files(plan, role, manifest)
    partial = sorted(str(item.relative_to(target)) for item in target.rglob('*') if item.is_file() and PARTIAL_MARK in item.name) if target.is_dir() else []
    base = dict(run_id=run_id, role=role, required_absent=[], partial_retained=partial, problems=[])
    seal_path = target / guest_runner.SEAL
    try:
        if not seal_path.exists():
            # A seal that failed its hash on the way back is kept apart, and a sealed role with corrupt bytes on record is not merely absent.
            damaged = any((run_dir / capacity_scorer.CORRUPT_EVIDENCE_DIR / role).glob(guest_runner.SEAL + '.*'))
            word = 'corrupt' if damaged else 'missing'
            return dict(base, status=word, files=[dict(path=guest_runner.SEAL, status=word)], required_absent=required)
        seal = json.loads(seal_path.read_text())
        digest = sha256_path(seal_path)
    except READ_FAILURES as error:
        return dict(base, status='corrupt', files=[dict(path=guest_runner.SEAL, status='unreadable', reason=type(error).__name__)], required_absent=required)
    listed = capacity_scorer.seal_inventory(seal, run_id, role)
    if listed is None:
        return dict(base, status='corrupt', files=[dict(path=guest_runner.SEAL, status='corrupt', reason='it is not a seal of this run and role')], required_absent=required, problems=['the seal here is not of %s %s' % (run_id, role)])
    problems = []
    stale = []
    if seal.get('schema') != guest_runner.SCHEMA:
        stale.append('the seal is schema %r, and this controller reads %r' % (seal.get('schema'), guest_runner.SCHEMA))
    if session_id is not None:
        expected = dict(session_id=session_id, manifest_sha256=manifest_sha256, run_id=run_id, current_token=token)
        try:
            contradicted = capacity_scorer.seal_reply_problems(run_dir, role, digest, seal, token, expected)
        except READ_FAILURES as error:
            contradicted = ['the records around it could not be read: ' + type(error).__name__]
        if contradicted:
            return dict(base, status='corrupt', files=[dict(path=guest_runner.SEAL, status='corrupt', reason='it disagrees with what is on record')], required_absent=required, problems=contradicted)
    files = [dict(path=guest_runner.SEAL, status='verified', sha256=digest)]
    for item in listed:
        files.append(dict(path=item['path'], status=file_status(target / item['path'], item['sha256']), sha256=item['sha256']))
    names = {item['path'] for item in listed}
    statuses = {entry['status'] for entry in files}
    overall = 'verified' if statuses == {'verified'} else ('corrupt' if statuses & {'corrupt', 'unreadable'} else 'missing')
    unlisted = sorted(str(item.relative_to(target)) for item in target.rglob('*') if item.is_file() and str(item.relative_to(target)) not in names and item.name != guest_runner.SEAL and PARTIAL_MARK not in item.name)
    if unlisted:
        problems.append('%d file(s) here are not in the seal' % len(unlisted))
    stale += _schema_problems(target, role, manifest, names)
    return dict(base, status=overall, files=files, required_absent=sorted(set(required) - names), problems=problems + stale, stale_schema=bool(stale), unlisted=unlisted)


def _schema_problems(target, role, manifest, names):
    """Bytes of the right hash from a recorder of another schema are stale evidence, whatever the transfer proved."""
    name = RECORDER_DOCUMENTS[role]
    frozen = ((manifest or {}).get('telemetry_schema') or {}).get('id')
    if name not in names or frozen is None:
        return []
    document = _read_json(target / name)
    found = document.get('schema') if isinstance(document, dict) else None
    return [] if found == frozen else ['%s %s is schema %r, and this session froze %r' % (role, name, found, frozen)]


# ---- what the whole session left ------------------------------------------------------------------------

def _listing(directory):
    """(the names this directory gave, the error that stopped it, if one did). What it gave before failing stays: an error part way through a listing says nothing about the names already seen, and a directory that could not be listed is not an empty one."""
    names = []
    try:
        with os.scandir(str(directory)) as scan:
            for entry in scan:
                names.append(entry.name)
    except OSError as error:
        return names, error
    return names, None


def _walk(session_dir):
    """(every regular file by relative path with its hash, what could not be held, what is not a plain file, every path this cannot vouch for). A file that moved while it was read cannot be vouched for by this reading, and what an unlistable directory holds is unknown."""
    session_dir = pathlib.Path(session_dir)
    files, problems, odd, absent = [], [], [], []
    pending = [session_dir]
    while pending:
        current = pending.pop()
        relative_dir = current.relative_to(session_dir)
        names, failure = _listing(current)
        if failure is not None:
            shown = str(relative_dir) if relative_dir.parts else '.'
            problems.append('directory %s could not be listed in full (%s), so what it holds is not all in this inventory' % (shown, type(failure).__name__))
            absent.append(dict(path=shown, kind='directory', reason=type(failure).__name__))
        for name in sorted(names):
            path = current / name
            relative = str(relative_dir / name) if relative_dir.parts else name
            try:
                before = os.lstat(str(path))
                if stat.S_ISDIR(before.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(before.st_mode):
                    odd.append(relative)
                    continue
                digest = sha256_path(path)
                after = os.lstat(str(path))
            except OSError as error:
                problems.append('%s could not be read: %s' % (relative, type(error).__name__))
                absent.append(dict(path=relative, kind='file', reason=type(error).__name__))
                continue
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                problems.append('%s changed while it was being read' % relative)
                absent.append(dict(path=relative, kind='file', reason='changed while it was read'))
                continue
            files.append(dict(path=relative, sha256=digest, size=after.st_size, kind=_file_kind(relative)))
    files.sort(key=lambda item: item['path'])
    absent.sort(key=lambda item: item['path'])
    return files, problems, sorted(odd), absent


def _file_kind(relative):
    if relative in APPEND_ONLY:
        return 'append_only'
    if PARTIAL_MARK in pathlib.PurePath(relative).name:
        return 'partial'
    if relative.startswith('runs/') and '/' + capacity_scorer.CORRUPT_EVIDENCE_DIR + '/' in relative:
        return 'corrupt_retained'
    return 'immutable'


def _exists(path):
    """Whether a name is there. A disk that will not say keeps it from reading as gone: only a real absence is one."""
    try:
        return pathlib.Path(path).exists()
    except OSError:
        return True


def _execution_records(run_dir):
    found = (_read_json(path) for path in sorted(pathlib.Path(run_dir).glob('execution*.json')))
    return [document for document in found if isinstance(document, dict)]


def _dispatched_runs(session_dir, runs):
    """Every run the registry or the search says was dispatched, and any directory beside them that shows one was: a grant, an execution record, a plan or a role's own tree. A plan that has gone does not take its run with it."""
    known = list(runs or ())
    root = pathlib.Path(session_dir) / 'runs'
    try:
        names = sorted(item.name for item in root.iterdir() if item.is_dir())
    except OSError:
        names = []

    def shows_dispatch(run_dir):
        return _exists(run_dir / 'grant.json') or bool(_execution_records(run_dir)) or any(_exists(run_dir / ('plan-%s.json' % role)) or _exists(run_dir / role) for role in ROLES)
    return known + [name for name in names if name not in known and shows_dispatch(root / name)]


def grant_facts(snapshot):
    """(run_id, role) to ``issued`` or ``started``, from the registry's own journal: durable, kept apart from this disk, and written before any plan was. An authorized start with no plan behind it is not proof that no process ever ran."""
    issued, facts = {}, {}
    for event in (snapshot or {}).get('journal') or ():
        data = event.get('data') if isinstance(event, dict) else None
        if not isinstance(data, dict):
            continue
        if event.get('kind') == 'guest_grant_issued' and data.get('run_id') is not None:
            issued[data.get('grant_id')] = (data['run_id'], data.get('role'))
            facts.setdefault((data['run_id'], data.get('role')), 'issued')
        elif event.get('kind') == 'guest_grant_started' and data.get('grant_id') in issued:
            facts[issued[data['grant_id']]] = 'started'
    return facts


def role_reach(run_dir, run_id, role, grants=None):
    """(what shows this role was meant for a host, what shows it got there), each a list of reasons. A plan that has gone proves nothing, so only the records kept apart from it can say a role never went."""
    run_dir = pathlib.Path(run_dir)
    meant, reached = [], []
    if _exists(run_dir / ('plan-%s.json' % role)):
        meant.append('its plan')
    fact = (grants or {}).get((run_id, role))
    if fact == 'issued':
        meant.append('its start grant')
    elif fact == 'started':
        reached.append('its started grant')
    for record in _execution_records(run_dir):
        for key, into in (('plan_digests', meant), ('roles', reached), ('exported', reached)):
            if isinstance(record.get(key), dict) and role in record[key]:
                into.append('its %s in an execution record' % key)
    if list(run_dir.glob('seal-receipt-*-%s-*.json' % role)):
        reached.append('a seal receipt')
    if _exists(run_dir / role):
        reached.append('its directory')
    if _exists(run_dir / capacity_scorer.CORRUPT_EVIDENCE_DIR / role):
        reached.append('corrupt bytes kept of it')
    return meant, reached


def required_session_files(session_dir, any_runs):
    """The session's own records. An empty journal is a fact and these missing are not: the three separate results all rest on them."""
    session_dir = pathlib.Path(session_dir)
    required = ['manifest.json', 'manifest.sha256']
    if any_runs:
        required += [do_session.JOURNAL, 'provisioning/journal.ndjson', 'provisioning/readiness.json', 'execution/journal.ndjson']

    def there(name):
        try:
            return (session_dir / name).is_file()
        except OSError:
            return False
    missing = [name for name in required if not there(name)]
    if any_runs and not any((session_dir / 'admissions').glob('*.json')):
        missing.append('admissions/')
    return missing


def _admissions_on_record(session_dir):
    """Each admission the search journal says decided a selection, by the time it names. A journal line is what makes one expected, and only that."""
    session_dir = pathlib.Path(session_dir)
    try:
        lines = (session_dir / do_session.JOURNAL).read_text().splitlines()
        names = [item.name for item in (session_dir / 'admissions').iterdir()]
    except OSError:
        return []
    missing = set()
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('kind') == 'selected' and row.get('admission_decision') == admission.ADMITTED and isinstance(row.get('selected_at'), str):
            stamp = row['selected_at'].replace(':', '').replace('+0000', 'Z')
            if not any(name.startswith(stamp + '-') for name in names):
                missing.add('admissions/%s-*.json' % stamp)
    return sorted(missing)


def _frozen_controller_files(manifest):
    """The controller's own inputs, from the pinned measurement schema, when this session froze the schema this revision reads. Otherwise there is no list to hold it to, and ``_schema_problems`` answers for the difference."""
    frozen = (manifest or {}).get('telemetry_schema') or {}
    if frozen.get('id') != mw.schema()['id'] or frozen.get('sha256') != mw.schema_sha256():
        return ()
    return tuple(mw.schema()['files'].get('controller') or ())


def controller_inputs(session_dir, entries, runs, manifest, snapshot=None):
    """What the controller itself has to have kept of each dispatched run, and what provisioning pinned, as the current producers write them. A score or a rendered report that still verifies stands in for none of it.

    Returns dict(missing, corrupt, by_run, problems): relative paths, what keeps each run from being vouched for, and what is the session's own. Each file named here is one a producer writes on the path that run took, so nothing is asked of a run that never got there.
    """
    session_dir = pathlib.Path(session_dir)
    missing, corrupt, by_run = [], [], {}
    frozen = _frozen_controller_files(manifest)
    by_role = {(entry['run_id'], entry['role']): entry for entry in entries}
    for run_id in runs:
        run_dir = session_dir / 'runs' / run_id
        notes = []

        def absent(name, why):
            missing.append('runs/%s/%s' % (run_id, name))
            notes.append('%s is missing, and %s' % (name, why))
        try:
            if not run_dir.is_dir():
                continue
            went = [role for role in ROLES if (run_id, role) in by_role and by_role[run_id, role]['status'] != 'never_created']
            for name in ('selected.json', 'grant.json'):
                if not _exists(run_dir / name):
                    absent(name, 'it is written when a run is selected and dispatched')
            if 'clock-before.json' in frozen and not _exists(run_dir / 'clock-before.json'):
                absent('clock-before.json', 'the frozen measurement schema requires it of a dispatched run')
            if 'clock-after.json' in frozen and went and not _exists(run_dir / 'clock-after.json'):
                absent('clock-after.json', 'the frozen measurement schema requires it once a role went to a host')
            if 'window-proof.json' in frozen and _exists(run_dir / capacity_scorer.SCORE_FILE) and not _exists(run_dir / 'window-proof.json'):
                absent('window-proof.json', 'the score of this run stands on it')
            records = _execution_records(run_dir)
            for role in went:
                _held_to_plan_and_receipt(run_dir, run_id, role, by_role[run_id, role], records, absent, corrupt, notes)
        except OSError as error:
            notes.append('the records of this run could not be read: %s' % type(error).__name__)
        if notes:
            by_run[run_id] = notes
    found = _provenance(session_dir, snapshot) if runs else dict(missing=[], corrupt=[], problems=[])
    return dict(missing=sorted(set(missing + found['missing'])), corrupt=sorted(set(corrupt + found['corrupt'])), by_run=by_run, problems=found['problems'])


def _held_to_plan_and_receipt(run_dir, run_id, role, entry, records, absent, corrupt, notes):
    """A role's plan against the digest an execution record bound, and its seal against a receipt written before any of its bytes were judged. A plan that has gone is on the role's own entry already, as a required file."""
    plan = run_dir / ('plan-%s.json' % role)
    if _exists(plan):
        document = _read_json(plan)
        recorded = {record['plan_digests'][role] for record in records if isinstance(record.get('plan_digests'), dict) and role in record['plan_digests']}
        if not isinstance(document, dict):
            corrupt.append('runs/%s/%s' % (run_id, plan.name))
            notes.append('%s cannot be read as a plan' % plan.name)
        elif recorded and run_plan.plan_digest(document) not in recorded:
            corrupt.append('runs/%s/%s' % (run_id, plan.name))
            notes.append('%s is not the plan the execution record bound' % plan.name)
    else:
        absent(plan.name, 'the records show this role was meant for a host')
    sealed = next((item.get('sha256') for item in entry.get('files') or () if item.get('path') == guest_runner.SEAL and item.get('status') == 'verified'), None)
    if sealed is not None:
        receipts = (_read_json(path) for path in run_dir.glob('seal-receipt-*-%s-*.json' % role))
        if not any(isinstance(item, dict) and item.get('seal_sha256') == sealed for item in receipts):
            absent('seal-receipt of %s' % role, 'every seal is held to one written before any of its bytes were judged')


def _provenance(session_dir, snapshot):
    """What the readiness report says provisioning left, each by path and the hash taken then, and that report against the hash the registry was given. Being in the inventory says a file is here, and only this says it is that file."""
    missing, corrupt, problems = [], [], []
    path = session_dir / 'provisioning' / 'readiness.json'
    for event in (snapshot or {}).get('journal') or ():
        reference = (event.get('data') or {}).get('evidence_ref') if isinstance(event, dict) and event.get('kind') == 'pair_ready' else None
        if isinstance(reference, str) and '#sha256:' in reference and _exists(path):
            try:
                if sha256_path(path) != reference.split('#sha256:')[1]:
                    corrupt.append('provisioning/readiness.json')
                    problems.append('provisioning/readiness.json is not the report the registry was given')
            except OSError as error:
                problems.append('provisioning/readiness.json could not be read: ' + type(error).__name__)
    readiness = _read_json(path)
    if not isinstance(readiness, dict):
        if _exists(path):
            corrupt.append('provisioning/readiness.json')
            problems.append('provisioning/readiness.json cannot be read')
        return dict(missing=missing, corrupt=corrupt, problems=problems)
    required = readiness.get('required_artifacts') if isinstance(readiness.get('required_artifacts'), list) else []
    if {item.get('role') for item in required if isinstance(item, dict)} != set(ROLES):
        problems.append('the readiness report does not name the required provisioning artifacts of both roles')
    for item in required:
        name = item.get('path') if isinstance(item, dict) else None
        pure = pathlib.PurePosixPath(name) if isinstance(name, str) and name else None
        if pure is None or pure.is_absolute() or '..' in pure.parts or not isinstance(item.get('sha256'), str):
            problems.append('the readiness report names a required artifact that cannot be held to a file of this session')
            continue
        try:
            if not (session_dir / name).is_file():
                missing.append(name)
                problems.append('%s is missing, and the readiness report requires it' % name)
            elif sha256_path(session_dir / name) != item['sha256']:
                corrupt.append(name)
                problems.append('%s is not the file the readiness report recorded' % name)
        except OSError as error:
            problems.append('%s could not be read: %s' % (name, type(error).__name__))
    return dict(missing=missing, corrupt=corrupt, problems=problems)


def role_entries(session_dir, runs, manifest, sha, token=ANY_TOKEN, never_created=(), snapshot=None):
    """(every role the durable records say was meant for a host, of every dispatched run, with its file list; what is gone). A plan that has gone proves nothing: the records around it decide, and a role they say nothing of never went. The host's own "no such run" stands only where nothing on record says it got there."""
    session_dir = pathlib.Path(session_dir)
    session_id = manifest['session']['id'] if isinstance(manifest, dict) else None
    grants = grant_facts(snapshot)
    entries, problems = [], []
    for run_id in runs:
        run_dir = session_dir / 'runs' / run_id
        try:
            there = run_dir.is_dir()
        except OSError as error:
            problems.append('the directory of dispatched run %s could not be read: %s' % (run_id, type(error).__name__))
            continue
        if not there:
            problems.append('the directory of dispatched run %s is gone' % run_id)
            continue
        for role in ROLES:
            try:
                meant, reached = role_reach(run_dir, run_id, role, grants)
                if (run_id, role) in never_created and not reached:
                    entries.append(dict(run_id=run_id, role=role, status='never_created', files=[], required_absent=[], partial_retained=[], problems=[]))
                elif meant or reached:
                    entry = role_inventory(run_dir, run_id, role, session_id, sha, manifest, token)
                    if (run_id, role) in never_created:
                        entry['problems'] = list(entry.get('problems') or ()) + ['the host says this role never existed, and %s say it did' % ', '.join(reached)]
                    if not _exists(run_dir / ('plan-%s.json' % role)):
                        entry['required_absent'] = sorted(set(entry.get('required_absent') or ()) | {'plan-%s.json' % role})
                        entry['problems'] = list(entry.get('problems') or ()) + ['plan-%s.json is gone, and %s say this role was meant for a host' % (role, ', '.join(meant + reached))]
                    entries.append(entry)
            except READ_FAILURES + (AttributeError,) as error:     # whatever a directory turned out to hold, it costs that role and nothing else
                entries.append(dict(run_id=run_id, role=role, status='corrupt', files=[dict(path=guest_runner.SEAL, status='unreadable', reason=type(error).__name__)], required_absent=[], partial_retained=[], problems=['this role could not be read: ' + type(error).__name__]))
    return entries, problems


def inventory(session_dir, runs, entries, manifest, sha, problems=(), controller=None):
    """Statuses and hashes. Nothing in here is read from a host, and nothing in here can raise for what a file turns out to hold."""
    session_dir = pathlib.Path(session_dir)
    controller = controller or dict(missing=[], corrupt=[], by_run={}, problems=[])
    files, read_problems, odd, not_inventoried = _walk(session_dir)
    problems = list(problems) + read_problems + list(controller['problems']) + ['%s: %s' % (run_id, note) for run_id, notes in sorted(controller['by_run'].items()) for note in notes]
    if odd:
        problems.append('%d path(s) here are not plain files, and are not vouched for: %s' % (len(odd), ', '.join(odd[:5])))
    session_id = (manifest or {}).get('session', {}).get('id') if isinstance(manifest, dict) else None
    missing_records = required_session_files(session_dir, bool(runs)) + (_admissions_on_record(session_dir) if runs else [])
    problems += ['session record %s is missing' % name for name in missing_records]
    statuses = {entry['status'] for entry in entries}
    if not runs and sha is not None:
        problems.append('no run was dispatched, so there is no measurement evidence to call complete')
    guards = []
    for run_id in runs:
        try:
            guards += [path.name for path in capacity_scorer.validation_guards(session_dir / 'runs' / run_id)]
        except OSError as error:
            problems.append('the validation guards could not be read: ' + type(error).__name__)
    if guards:
        problems.append('%d comparison(s) of transferred bytes never reported an end' % len(guards))
    status = 'complete'
    if 'corrupt' in statuses or controller['corrupt']:
        status = 'corrupt'
    elif 'missing' in statuses or missing_records or controller['missing']:
        status = 'missing'
    elif problems or any(entry.get('required_absent') or entry.get('problems') for entry in entries):
        status = 'partial'     # an earlier failed attempt kept beside a file that later verified costs nothing: it is what happened, and it is on the list
    if any(entry.get('stale_schema') for entry in entries) or not _manifest_on_record(session_dir, sha):
        status = 'corrupt'
    sums = _sums_text(files)
    return dict(schema=INVENTORY_SCHEMA, session_id=session_id, manifest_sha256=sha, status=status, problems=sorted(set(problems + [item for entry in entries for item in entry.get('problems') or ()])), required_session_missing=missing_records, controller_inputs=dict(missing=controller['missing'], corrupt=controller['corrupt'], by_run=controller['by_run']), not_inventoried=not_inventoried,
                roles=[{key: value for key, value in entry.items() if key != 'files'} | dict(files=len(entry.get('files') or ()), not_verified=[item for item in entry.get('files') or () if item['status'] != 'verified']) for entry in entries],
                file_count=len(files), total_bytes=sum(item['size'] for item in files), sums_sha256=evidence_publication.sha256_bytes(sums.encode('utf-8')), files=files, partial_files=[item['path'] for item in files if item['kind'] == 'partial'], corrupt_files=[item['path'] for item in files if item['kind'] == 'corrupt_retained'], not_plain_files=odd,
                admissions=len([item for item in files if item['path'].startswith('admissions/')]), attempts_retained=len([item for item in files if item['kind'] == 'partial']))


def _manifest_on_record(session_dir, sha):
    if sha is None:
        return False
    try:
        return (pathlib.Path(session_dir) / 'manifest.sha256').read_text().split()[0] == sha
    except (OSError, IndexError):
        return False


def _sums_text(files):
    return ''.join('%s  %s\n' % (item['sha256'], item['path']) for item in files)


def published_sums(files, generation):
    """The inventory that goes public. A journal goes on growing after this, so its line names the copy this export kept of exactly those bytes, which will still match in ten years."""
    lines = []
    for item in files:
        path = '%s/%s/%s/%s' % (EXPORT_DIR, generation, JOURNALS, item['path']) if item['kind'] == 'append_only' else item['path']
        lines.append('%s  %s\n' % (item['sha256'], evidence_publication.published_path(path)))
    return ''.join(lines)


# ---- one generation -------------------------------------------------------------------------------------

@dataclasses.dataclass
class Exported:
    status: str
    generation: str = None
    ref: str = None
    problems: list = dataclasses.field(default_factory=list)
    publication_refused: list = dataclasses.field(default_factory=list)


def registry_snapshot(client, session_id):
    """What the registry says now, kept as a file so a report never has to ask again. A registry that cannot answer leaves that fact and costs nothing else."""
    if client is None:
        return dict(unavailable='no registry was consulted')
    try:
        snapshot = dict(as_of=client.call('health', session_id=session_id).get('evaluated_at'), status=client.call('status', session_id=session_id), journal=client.call('journal', session_id=session_id), verify_journal=client.call('verify_journal'))
    except (registry_client.RegistryRejected, registry_client.RegistryUnavailable) as error:
        return dict(unavailable=getattr(error, 'code', type(error).__name__))
    if manifest_mod.scan_for_secrets(snapshot):
        return dict(unavailable='the registry reply held a credential value and was not kept')
    return snapshot


def _load_invoices(session_dir):
    found = []
    for path in sorted((pathlib.Path(session_dir) / INVOICE_DIR).glob('*.json')):
        document = _read_json(path)
        if isinstance(document, dict) and document.get('schema') == INVOICE_SCHEMA:
            found.append({key: document.get(key) for key in ('period', 'amount_usd', 'source', 'recorded_at')})
    return found


def _next_generation(session_dir):
    root = pathlib.Path(session_dir) / EXPORT_DIR
    root.mkdir(parents=True, exist_ok=True)
    taken = [item.name for item in root.iterdir() if item.name.startswith('gen-') and item.is_dir() and do_session.WRITING not in item.name]
    highest = max((int(name.split('-')[1]) for name in taken if name.split('-')[1].isdigit()), default=0)
    return GENERATION_NAME % (highest + 1)


def _retain_run_summaries(session_dir, capacity, role_entries, generation, sensitive, by_run=None):
    """``runs/<run_id>/summary.json`` and ``REPORT.md``, create-only. A later export that sees something new keeps its own copy beside them and never rewrites the first."""
    session_dir = pathlib.Path(session_dir)
    problems = []
    roles = {}
    for entry in role_entries:
        roles.setdefault(entry['run_id'], {})[entry['role']] = {key: entry.get(key) for key in ('status', 'required_absent', 'partial_retained', 'problems')}
    for row in capacity['trials']:
        run_dir = session_dir / 'runs' / row['run_id']
        try:
            if not run_dir.is_dir():
                continue
            summary = session_report.scrub(session_report.run_summary(session_dir, row, roles.get(row['run_id'], {}), (by_run or {}).get(row['run_id'], ())), sensitive)
            if manifest_mod.scan_for_secrets(summary):
                raise ValueError('it held a credential value')
            for name, text in (('summary.json', session_report.canonical(summary)), ('REPORT.md', session_report.render_run(summary))):
                path = run_dir / name
                if path.exists() and path.read_text() == text:
                    continue
                if path.exists():
                    stem, suffix = name.split('.')
                    path = run_dir / ('%s-%s.%s' % (stem, generation, suffix))
                do_session.write_new(path, text)
        except READ_FAILURES as error:
            problems.append('the summary of run %s was not retained: %s' % (row['run_id'], type(error).__name__))
    return problems


def _reports(session_dir, generation, inventory_document, snapshot, capacity, invoices, publication, sensitive):
    """Every derived file of one generation, from its inputs alone. ``reproduce`` calls exactly this."""
    document = session_report.scrub(session_report.build(session_dir, inventory_document, snapshot, capacity, invoices, publication), sensitive)
    if manifest_mod.scan_for_secrets(document):
        raise ValueError('the report held a credential value after scrubbing, and was not written')
    derived = {REPORT_JSON: session_report.canonical(document).encode('utf-8'), REPORT_MD: session_report.render(document).encode('utf-8')}
    sums = published_sums(inventory_document['files'], generation).encode('utf-8')
    summary = session_report.compact(document, evidence_publication.sha256_bytes(sums), inventory_document['file_count'], inventory_document['total_bytes'])
    text = {'summary.json': session_report.canonical(summary).encode('utf-8'), 'summary.md': session_report.render_compact(summary).encode('utf-8'), 'SHA256SUMS': sums}
    refused = evidence_publication.guard_problems(text, sensitive)
    if not refused:
        derived.update({PUBLISHED + '/' + name: data for name, data in text.items()})
    return derived, refused


def _sealed_write(top, relative, data):
    path = top / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_tree(top):
    for directory, names, _ in os.walk(str(top), topdown=False):
        do_session._fsync_directory(directory)


def export_session(session_dir, client=None, runs=None, token=ANY_TOKEN, never_created=(), failpoint=None):
    """One new generation, whole or not at all. Never raises for what it finds, and a failure says what it cost: the session's cleanup does not depend on this."""
    session_dir = pathlib.Path(session_dir)
    failpoint = failpoint or (lambda name: None)
    problems = []
    manifest, sha = None, None
    try:
        manifest, sha, _, _ = do_session.load_session(session_dir)
    except (manifest_mod.ManifestError, *READ_FAILURES) as error:
        problems.append('the manifest does not hold up: ' + cleanup_provider.redact(error))
    if manifest is None:
        return _manifest_gone(session_dir, problems, runs, failpoint)
    session_id = manifest['session']['id']
    snapshot = registry_snapshot(client, session_id)
    status = snapshot.get('status') if isinstance(snapshot.get('status'), dict) else None
    if status is not None and status.get('manifest_sha256') != sha:
        problems.append('the registry holds another manifest for this session')
    if status is not None and runs is None:
        runs = [item['run_id'] for item in status.get('runs') or ()]
    sensitive = evidence_publication.sensitive_values(session_dir, manifest, snapshot)
    capacity = None
    try:
        capacity = capacity_report.build(session_dir)
    except READ_FAILURES + (manifest_mod.ManifestError,) as error:
        problems.append('the search journal does not hold up: ' + type(error).__name__)
    if runs is None:
        runs = [row['run_id'] for row in capacity['trials']] if capacity else []
    runs = _dispatched_runs(session_dir, runs)
    entries, gone = role_entries(session_dir, runs, manifest, sha, token, never_created, snapshot)
    problems += gone
    controller = controller_inputs(session_dir, entries, runs, manifest, snapshot)
    try:
        generation = _next_generation(session_dir)
    except OSError as error:
        return Exported('partial', problems=problems + ['no export directory: ' + type(error).__name__])
    if capacity is not None:
        if capacity['evidence']['disputed_trials']:
            problems.append('%d trial(s) disagree with their retained files' % len(capacity['evidence']['disputed_trials']))
        problems += _retain_run_summaries(session_dir, capacity, entries, generation, sensitive, controller['by_run'])
    document = inventory(session_dir, runs, entries, manifest, sha, problems, controller)
    return _write_generation(session_dir, document, snapshot, capacity, _load_invoices(session_dir), evidence_publication.publication_status(session_dir), manifest, sensitive, failpoint, generation)


def _manifest_gone(session_dir, problems, runs, failpoint):
    document = inventory(session_dir, _dispatched_runs(session_dir, runs), [], None, None, problems)
    return _write_generation(session_dir, dict(document, status='corrupt'), dict(unavailable='no manifest to ask about'), None, (), None, None, (), failpoint)


def _write_generation(session_dir, document, snapshot, capacity, invoices, publication, manifest, sensitive, failpoint, generation=None):
    session_dir = pathlib.Path(session_dir)
    top = None
    try:
        generation = generation or _next_generation(session_dir)
        root = session_dir / EXPORT_DIR
        top = pathlib.Path(tempfile.mkdtemp(prefix=generation + do_session.WRITING, dir=str(root)))
        refused, derived = [], {}
        inputs = {'registry.json': snapshot, 'invoices.json': list(invoices), 'publication.json': publication or dict(status='not_published')}
        if capacity is not None:
            inputs['capacity.json'] = capacity
        if capacity is not None and manifest is not None:
            try:
                derived, refused = _reports(session_dir, generation, document, snapshot, capacity, list(invoices), publication, sensitive)
            except READ_FAILURES as error:
                document = dict(document, problems=sorted(set(document['problems'] + ['no report was written: ' + type(error).__name__])), status=_worse(document['status'], 'partial'), report_refused=type(error).__name__)
        if refused:
            document = dict(document, publication_refused=refused)
        _sealed_write(top, INVENTORY_FILE, session_report.canonical(document).encode('utf-8'))
        _sealed_write(top, SUMS_FILE, _sums_text(document['files']).encode('utf-8'))
        for name, value in inputs.items():
            _sealed_write(top, INPUTS + '/' + name, session_report.canonical(value).encode('utf-8'))
        for name, data in derived.items():
            _sealed_write(top, name, data)
        for item in document['files']:
            if item['kind'] == 'append_only':
                with (session_dir / item['path']).open('rb') as handle:
                    held = handle.read(item['size'])
                if evidence_publication.sha256_bytes(held) != item['sha256']:
                    raise OSError('%s changed under this export' % item['path'])
                _sealed_write(top, JOURNALS + '/' + item['path'], held)
        failpoint('before_generation_rename')
        _sync_tree(top)
        final = root / generation
        os.rename(str(top), str(final))     # atomic, onto a name nothing holds: only a whole generation ever has it
        do_session._fsync_directory(root)
    except OSError as error:
        return Exported(_worse(document['status'], 'partial'), problems=list(document['problems']) + ['the generation was not written: ' + type(error).__name__], publication_refused=[])
    ref = '%s/%s/%s#sha256:%s' % (EXPORT_DIR, generation, INVENTORY_FILE, sha256_path(final / INVENTORY_FILE))
    return Exported(document['status'], generation, ref, list(document['problems']), refused)


def _worse(status, other):
    return min((status, other), key=STATUS_ORDER.index)


def latest_generation(session_dir):
    root = pathlib.Path(session_dir) / EXPORT_DIR
    names = sorted(item.name for item in root.glob('gen-*') if item.is_dir() and do_session.WRITING not in item.name)
    if not names:
        raise ValueError('this session has no export yet')
    return names[-1]


def verify(session_dir, generation=None):
    """Every recorded hash against the disk. An append-only journal must still begin with exactly what it held, and may have grown. Returns problems, by path."""
    session_dir = pathlib.Path(session_dir)
    generation = generation or latest_generation(session_dir)
    document = _read_json(session_dir / EXPORT_DIR / generation / INVENTORY_FILE)
    if not isinstance(document, dict):
        return ['%s has no readable inventory' % generation]
    problems = []
    for item in document.get('files') or ():
        path = session_dir / item['path']
        try:
            if item['kind'] == 'append_only':
                with path.open('rb') as handle:
                    head = handle.read(item['size'])
                if len(head) != item['size'] or evidence_publication.sha256_bytes(head) != item['sha256']:
                    problems.append('%s no longer begins with what it held' % item['path'])
            elif sha256_path(path) != item['sha256']:
                problems.append('%s is not the file that was recorded' % item['path'])
        except OSError as error:
            problems.append('%s could not be read: %s' % (item['path'], type(error).__name__))
    sums = (session_dir / EXPORT_DIR / generation / SUMS_FILE)
    try:
        if evidence_publication.sha256_bytes(sums.read_bytes()) != document.get('sums_sha256'):
            problems.append('%s is not the inventory the export wrote' % SUMS_FILE)
    except OSError as error:
        problems.append('%s could not be read: %s' % (SUMS_FILE, type(error).__name__))
    return problems


def reproduce(session_dir, generation=None):
    """Every report of a generation again from that generation's retained inputs. Returns the names that differ. A difference means a raw file changed or the reporting code did, and neither is for this to decide."""
    session_dir = pathlib.Path(session_dir)
    generation = generation or latest_generation(session_dir)
    top = session_dir / EXPORT_DIR / generation
    document = _read_json(top / INVENTORY_FILE)
    capacity = _read_json(top / INPUTS / 'capacity.json')
    if not isinstance(document, dict):
        return [INVENTORY_FILE]
    if capacity is None or document.get('report_refused'):
        return []     # a generation with no report has nothing to reproduce, and says so in its inventory
    manifest = _read_json(session_dir / 'manifest.json')
    if not isinstance(manifest, dict):
        return ['manifest.json']
    snapshot, invoices, publication = _read_json(top / INPUTS / 'registry.json'), _read_json(top / INPUTS / 'invoices.json'), _read_json(top / INPUTS / 'publication.json')
    sensitive = evidence_publication.sensitive_values(session_dir, manifest, snapshot)
    source = {key: value for key, value in document.items() if key not in ('publication_refused', 'report_refused')}
    try:
        derived, _ = _reports(session_dir, generation, source, snapshot, capacity, invoices, publication, sensitive)
    except READ_FAILURES + (AttributeError,) as error:
        return ['the reports cannot be rebuilt from what is here: ' + type(error).__name__]
    different = []
    for name, data in sorted(derived.items()):
        try:
            if (top / name).read_bytes() != data:
                different.append(name)
        except OSError:
            different.append(name)
    return different


def record_invoice(session_dir, period, amount_usd, source, now):
    """A provider charge, recorded later and by hand. It joins the next generation and changes no earlier one."""
    amount = float(amount_usd)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError('an invoice amount is a finite, non-negative number')
    document = dict(schema=INVOICE_SCHEMA, period=str(period), amount_usd=amount, source=str(source), recorded_at=str(now))
    if manifest_mod.scan_for_secrets(document):
        raise ValueError('an invoice fact may not hold a credential value')
    directory = pathlib.Path(session_dir) / INVOICE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(10000):
        path = directory / ('invoice-%04d.json' % attempt)
        if not path.exists():
            do_session.write_new_durable(path, json.dumps(document, indent=2, sort_keys=True) + '\n')
            return path
    raise ValueError('too many invoice facts')


# ---- the command line -----------------------------------------------------------------------------------

def _client(command):
    if not command:
        return None
    return registry_client.RegistryClient(registry_client.SubprocessTransport(shlex.split(command)), 'session-export')


def cmd_export(args):
    result = export_session(args.session_dir, client=_client(args.registry_command))
    print(json.dumps(dataclasses.asdict(result), indent=2, sort_keys=True))
    return 0 if result.status == 'complete' and not result.problems else 2


def cmd_verify(args):
    problems = verify(args.session_dir, args.generation)
    print(json.dumps(dict(ok=not problems, problems=problems), indent=2))
    return 0 if not problems else 2


def cmd_reproduce(args):
    different = reproduce(args.session_dir, args.generation)
    print(json.dumps(dict(identical=not different, different=different), indent=2))
    return 0 if not different else 2


def cmd_publish(args):
    session_dir = pathlib.Path(args.session_dir)
    generation = args.generation or latest_generation(session_dir)
    manifest = json.loads((session_dir / 'manifest.json').read_text())
    destination = evidence_publication.destination_for(args.docs_root, args.repository)
    receipts = evidence_publication.publish(session_dir, generation, [destination], args.now, evidence_publication.sensitive_values(session_dir, manifest))
    print(json.dumps(dict(receipts=receipts, status=evidence_publication.publication_status(session_dir)), indent=2, sort_keys=True))
    return 0 if all(item['status'] != evidence_publication.FAILED for item in receipts) else 2


def cmd_record_publication(args):
    print(json.dumps(evidence_publication.record_publication(args.session_dir, args.generation, args.reference, args.now, args.summary_sha256, args.operator), indent=2, sort_keys=True))
    return 0


def cmd_record_journal(args):
    print(json.dumps(evidence_publication.record_mirror(args.session_dir, args.generation, args.url, args.now, args.summary_sha256), indent=2, sort_keys=True))
    return 0


def cmd_record_invoice(args):
    print(record_invoice(args.session_dir, args.period, args.amount_usd, args.source, args.now))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    def command(name, func):
        item = sub.add_parser(name)
        item.add_argument('--session-dir', required=True)
        item.set_defaults(func=func)
        return item

    command('export', cmd_export).add_argument('--registry-command')
    command('verify', cmd_verify).add_argument('--generation')
    command('reproduce', cmd_reproduce).add_argument('--generation')
    publish = command('prepare-publication', cmd_publish)
    publish.add_argument('--generation')
    publish.add_argument('--now', required=True)
    publish.add_argument('--docs-root')
    publish.add_argument('--repository', default=str(pathlib.Path(__file__).parents[2]))
    recorded = command('record-publication', cmd_record_publication)
    recorded.add_argument('--generation', required=True)
    recorded.add_argument('--reference', required=True)
    recorded.add_argument('--summary-sha256', required=True)
    recorded.add_argument('--operator', required=True)
    recorded.add_argument('--now', required=True)
    journal = command('record-journal', cmd_record_journal)
    journal.add_argument('--generation', required=True)
    journal.add_argument('--url', required=True)
    journal.add_argument('--summary-sha256', required=True)
    journal.add_argument('--now', required=True)
    invoice = command('record-invoice', cmd_record_invoice)
    invoice.add_argument('--period', required=True)
    invoice.add_argument('--amount-usd', required=True)
    invoice.add_argument('--source', required=True)
    invoice.add_argument('--now', required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except evidence_publication.PublicationRefused as refused:
        print(json.dumps(dict(ok=False, code=refused.code, detail=cleanup_provider.redact(refused.detail))), file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(json.dumps(dict(ok=False, error=type(error).__name__ + ': ' + cleanup_provider.redact(error))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
