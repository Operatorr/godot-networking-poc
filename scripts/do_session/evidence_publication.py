"""The text that may leave the laptop, and where it goes (issue #70, amended by issue #63).

Raw evidence is never published. It stays private under ``loadtest-runs/digitalocean/<session_id>/`` on the operator's laptop, one copy, by accepted risk. What is published is text only: a compact summary, its machine-readable
JSON and a SHA256 inventory of the raw files. The canonical copy is ``docs/netcode/perf-notes/digitalocean-capacity/`` in this repository, and the reader-facing copy is a Journal page on marrowtech.app derived from the same text.

    guard_problems(files, sensitive)                 whether these bytes may leave at all, without saying what was found
    RepositoryDocs(root)                             the canonical destination: create-only files read back by hash
    publish(session_dir, generation, destinations)   one receipt per destination. A failure at one costs only that one
    record_mirror(...)                               what the operator says they did by hand. Recorded as that, and nothing more
    publication_status(session_dir)                  what is on record, with "not published" as the honest default

Nothing here posts to any site, opens a connection or reads an account. The Journal mirror is a seam: a destination may implement it, and until one does, or the operator records doing it, the mirror reads ``not_published``.
A local path is never called published evidence, and a receipt only exists once the bytes were read back and matched.
"""
import hashlib
import ipaddress
import json
import pathlib
import re

import do_session
import manifest as manifest_mod

CANONICAL_ROOT = 'docs/netcode/perf-notes/digitalocean-capacity'
SESSIONS_DIR = 'sessions'
DESTINATION_PREFIX = 'text-summary:'
AMENDED_DESTINATION = DESTINATION_PREFIX + CANONICAL_ROOT
MIRROR_NAME = 'marrowtech.app-journal'
RECEIPT_SCHEMA = 'omega.do-session.publication-receipt/1'
PUBLICATION_DIR = 'publication'
PUBLISHED_FILES = ('summary.md', 'summary.json', 'SHA256SUMS')
MAX_PUBLISHED_BYTES = 1024 * 1024       # the accepted model is "well under 1 MB" of prose and tables
SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$')
SAFE_PATH = re.compile(r'^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$')
# Shapes that say where a host is or how to reach it. Anything like these in published text stops the publication, whatever field carried it.
LEAK_PATTERNS = (
    ('an IPv4 address', re.compile(r'(?<!\d)\d{1,3}(?:\.\d{1,3}){3}(?!\d)')),
    ('a kernel socket endpoint', re.compile(r'\b[0-9A-Fa-f]{8}(?:[0-9A-Fa-f]{24})?:[0-9A-Fa-f]{4}\b')),
    ('a home directory or private path', re.compile(r'/(?:Users|home|root|etc)/|file:|ref:management-host|deployment/hetzner/ssh')),
    ('an SSH key fingerprint', re.compile(r'SHA256:[A-Za-z0-9+/]{20,}')),
    ('a private key or token assignment', re.compile(r'(?i)\b(?:password|passwd|secret|api[_-]?key|private[_-]?key|authorization)\s*[=:]')),
)


IPV6_CANDIDATE = re.compile(r'(?<![0-9A-Za-z:.])[0-9A-Fa-f.]*:[0-9A-Fa-f:.]*(?![0-9A-Za-z:.])')


def _holds_ipv6(text):
    for match in IPV6_CANDIDATE.finditer(text):
        try:
            if ipaddress.ip_address(match.group(0)).version == 6:
                return True
        except ValueError:
            continue
    return False


class PublicationRefused(Exception):
    def __init__(self, code, detail=''):
        super().__init__('%s: %s' % (code, detail))
        self.code = code
        self.detail = str(detail)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def destination_problems(manifest):
    """Whether a manifest names the amended text destination. A bucket or a release asset is not what the operator accepted, and neither is no destination at all."""
    reference = (manifest.get('evidence') or {}).get('durable_destination')
    if reference == AMENDED_DESTINATION:
        return []
    return ['evidence.durable_destination is %r, and only the accepted text model %r can be published to' % (reference, AMENDED_DESTINATION)]


def guard_problems(files, sensitive=()):
    """Every reason these bytes may not leave. Each names a file and a kind of thing and never the value, since a report of a leak must not be one."""
    problems = []
    total = 0
    for name, data in sorted(files.items()):
        total += len(data)
        if not isinstance(data, bytes):
            problems.append('%s is not bytes' % name)
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            problems.append('%s is not UTF-8 text' % name)
            continue
        if '\x00' in text:
            problems.append('%s holds binary data' % name)
        if manifest_mod.scan_for_secrets(text):
            problems.append('%s holds a credential value' % name)
        for label, pattern in LEAK_PATTERNS:
            if pattern.search(text):
                problems.append('%s holds %s' % (name, label))
        if _holds_ipv6(text):
            problems.append('%s holds an IPv6 address' % name)
        if any(item and item in text for item in sensitive):
            problems.append('%s holds a value registered as sensitive for this session' % name)
    if total > MAX_PUBLISHED_BYTES:
        problems.append('the publication is %d bytes, over the %d the accepted model allows' % (total, MAX_PUBLISHED_BYTES))
    return problems


def published_path(relative):
    """A path in the published inventory says nothing it does not have to. One that is not plainly a file name is published as a hash of itself."""
    plain = SAFE_PATH.match(relative) and not _holds_ipv6(relative) and not any(pattern.search(relative) for _, pattern in LEAK_PATTERNS)
    return relative if plain else 'opaque-path-sha256-' + sha256_bytes(relative.encode('utf-8', 'surrogateescape'))


class RepositoryDocs:
    """The canonical copy: ``<root>/sessions/<session_id>/<generation>/``. Create-only, and read back by hash before anyone is told it landed.

    ``root`` must be the canonical directory, so nothing can land beside a historical series such as ``hill-climb`` or the CAX11 reports. It writes the working tree and commits nothing: a commit stays the operator's or a pull request's.
    """
    name = 'repository-docs'

    def __init__(self, root):
        self.root = pathlib.Path(root)
        if self.root.resolve().parts[-len(pathlib.Path(CANONICAL_ROOT).parts):] != pathlib.Path(CANONICAL_ROOT).parts:
            raise PublicationRefused('destination_not_canonical', 'only %s holds published DigitalOcean evidence' % CANONICAL_ROOT)

    def reference(self, session_id, generation):
        return '%s/%s/%s/%s' % (CANONICAL_ROOT, SESSIONS_DIR, session_id, generation)

    def _directory(self, session_id, generation):
        return self.root / SESSIONS_DIR / session_id / generation

    def put(self, session_id, generation, files):
        directory = self._directory(session_id, generation)
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in sorted(files.items()):
            target = directory / name
            if target.exists():
                if target.read_bytes() == data:
                    continue
                raise PublicationRefused('published_file_differs', '%s already holds other bytes, and published text is never replaced' % name)
            do_session.write_new_durable_bytes(target, data)

    def read_back(self, session_id, generation, name):
        return (self._directory(session_id, generation) / name).read_bytes()


def _generation_files(session_dir, generation):
    directory = pathlib.Path(session_dir) / 'export' / generation / 'published'
    files = {}
    for name in PUBLISHED_FILES:
        try:
            files[name] = (directory / name).read_bytes()
        except OSError as error:
            raise PublicationRefused('nothing_to_publish', '%s of %s: %s' % (name, generation, type(error).__name__))
    return files


def _write_receipt(session_dir, document):
    if manifest_mod.scan_for_secrets(document):
        raise PublicationRefused('receipt_held_a_credential', 'not written')
    directory = pathlib.Path(session_dir) / PUBLICATION_DIR
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(10000):
        path = directory / ('receipt-%04d.json' % attempt)
        if not path.exists():
            do_session.write_new_durable(path, json.dumps(document, indent=2, sort_keys=True) + '\n')
            return path
    raise PublicationRefused('too_many_receipts')


def publish(session_dir, generation, destinations, now, sensitive=()):
    """Only the text the export wrote, only past the guard, and only ever a receipt for what was read back. One destination's failure leaves the others' receipts and says what happened to it."""
    session_dir = pathlib.Path(session_dir)
    manifest = json.loads((session_dir / 'manifest.json').read_text())
    session_id = manifest['session']['id']
    if not SAFE_NAME.match(session_id):
        raise PublicationRefused('unsafe_session_id')
    problems = destination_problems(manifest)
    if problems:
        raise PublicationRefused('destination_not_accepted', problems[0])
    if manifest.get('provider') != 'digitalocean':
        raise PublicationRefused('not_digitalocean_evidence', 'this destination holds DigitalOcean evidence only')
    files = _generation_files(session_dir, generation)
    problems = guard_problems(files, sensitive)
    if problems:
        raise PublicationRefused('guard_refused', '; '.join(problems))
    hashes = {name: sha256_bytes(data) for name, data in files.items()}
    receipts = []
    for destination in destinations:
        document = dict(schema=RECEIPT_SCHEMA, session_id=session_id, generation=generation, destination=destination.name, at=now, files=hashes)
        try:
            destination.put(session_id, generation, files)
            for name, digest in hashes.items():
                if sha256_bytes(destination.read_back(session_id, generation, name)) != digest:
                    raise PublicationRefused('read_back_mismatch', name)
            document.update(status='published', reference=destination.reference(session_id, generation))
        except (OSError, PublicationRefused) as error:
            document.update(status='failed', reference=None, code=getattr(error, 'code', type(error).__name__))
        _write_receipt(session_dir, document)
        receipts.append(document)
    return receipts


def record_mirror(session_dir, generation, url, now, derived_from_sha256):
    """The operator derived a Journal page from this generation's text and says where it is. It is recorded as their statement: nothing here fetched it, so it never reads as checked."""
    session_dir = pathlib.Path(session_dir)
    manifest = json.loads((session_dir / 'manifest.json').read_text())
    files = _generation_files(session_dir, generation)
    if derived_from_sha256 != sha256_bytes(files['summary.md']):
        raise PublicationRefused('mirror_of_other_text', 'this is not the hash of the %s summary' % generation)
    if not isinstance(url, str) or not url.startswith('https://marrowtech.app/'):
        raise PublicationRefused('mirror_not_the_accepted_site', 'the reader-facing copy is a marrowtech.app Journal page')
    document = dict(schema=RECEIPT_SCHEMA, session_id=manifest['session']['id'], generation=generation, destination=MIRROR_NAME, at=now, files=dict(derived_from=derived_from_sha256), status='operator_recorded', reference=url, checked_by_this_tool=False)
    _write_receipt(session_dir, document)
    return document


def publication_status(session_dir):
    """What is on record for this session. The default is that nothing was published, and an unreadable receipt proves nothing."""
    directory = pathlib.Path(session_dir) / PUBLICATION_DIR
    receipts, problems = [], []
    try:
        paths = sorted(directory.glob('receipt-*.json'))
    except OSError:
        paths = []
    for path in paths:
        if path.name.startswith('receipt-') and do_session.WRITING in path.name:
            continue
        try:
            receipts.append(json.loads(path.read_text()))
        except (OSError, ValueError) as error:
            problems.append('%s: %s' % (path.name, type(error).__name__))
    latest = {}
    for item in receipts:
        if isinstance(item, dict) and isinstance(item.get('destination'), str):
            latest[item['destination']] = item
    repository = latest.get(RepositoryDocs.name) or {}
    mirror = latest.get(MIRROR_NAME) or {}
    status = 'published' if repository.get('status') == 'published' else ('failed' if repository else 'not_published')
    return dict(status=status, repository=dict(status=repository.get('status', 'not_published'), reference=repository.get('reference'), generation=repository.get('generation')), journal_mirror=dict(status=mirror.get('status', 'not_published'), reference=mirror.get('reference'), checked_by_this_tool=False), receipts=len(receipts), problems=problems, raw_evidence='private on the operator\'s laptop, never published')


def sensitive_values(session_dir, manifest, registry=None):
    """What this session's own records say must not leave: its allowlisted addresses, the hosts' addresses, and where its credentials live. Only ever used to refuse."""
    found = set()
    allowlists = manifest.get('access_allowlists') or {}
    for key in ('ssh_sources', 'operator_udp_sources'):
        for item in allowlists.get(key) or ():
            found.update((str(item), str(item).split('/')[0]))
    for item in (manifest.get('credentials') or {}).values():
        found.add(str(item))
    found.add(str((manifest.get('ssh_key') or {}).get('private_key_ref')))
    found.add(str((manifest.get('ssh_key') or {}).get('fingerprint_sha256')))
    readiness_path = pathlib.Path(session_dir) / 'provisioning' / 'readiness.json'
    try:
        readiness = json.loads(readiness_path.read_text())
    except (OSError, ValueError):
        readiness = {}
    for role in (readiness.get('roles') or {}).values():
        address = ((role or {}).get('host_key') or {}).get('address') if isinstance(role, dict) else None
        if address:
            found.add(str(address))
    return sorted(item for item in found if item and item != 'None')


def destination_for(path_or_none, repository):
    return RepositoryDocs(pathlib.Path(path_or_none) if path_or_none else pathlib.Path(repository) / CANONICAL_ROOT)
