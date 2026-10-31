"""Freeze an immutable, hashed DigitalOcean test-session manifest from explicit conditions.

Slice 1 of the accepted controller handoff (issue #61). The manifest is the only input the
admission check and adaptive planner trust. Freezing REJECTS instead of substituting: every
hardware/image/network/source/workload choice must be stated explicitly and must match the
preflight facts observed through the authenticated API. Nothing here contacts a provider.

Terminology (docs/CONTEXT.md and issues #59/#60): a *test session* owns one game/bot Droplet
pair with one fixed hardware condition; its *test batch* is the frozen search policy; a
*test run* is one fresh workload execution. These are infrastructure terms, not the gameplay
Instance/Tick/Frame/Snapshot.
"""
import datetime
import hashlib
import json
import re

MANIFEST_SCHEMA = 'omega.do-session.manifest/1'
PROVIDER = 'digitalocean'
REGION = 'sgp1'
PROJECT_ID = 'eb8ab36b-8d7a-4af4-b28b-a66d1b9fe940'   # existing omega.realm project (#62)
SESSION_KINDS = ('calibration', 'lifecycle_smoke', 'capacity')

# Accepted game-host conditions (#60 §1, #61 §1). Prices are NOT trusted from this table: the
# live preflight supplies them and the manifest records what the API said, with quote time.
GAME_CONDITIONS = {
    's-1vcpu-1gb-amd': dict(kind='primary', vcpus=1, memory_mib=1024, nominal_monthly_usd=7.0,
                            display='premium-amd-1vcpu-1g', requires_memory_pressure_from=None),
    's-2vcpu-2gb-amd': dict(kind='primary', vcpus=2, memory_mib=2048, nominal_monthly_usd=21.0,
                            display='premium-amd-2vcpu-2g', requires_memory_pressure_from=None),
    's-1vcpu-2gb-amd': dict(kind='conditional', vcpus=1, memory_mib=2048, nominal_monthly_usd=14.0,
                            display='premium-amd-1vcpu-2g', requires_memory_pressure_from='s-1vcpu-1gb-amd'),
    's-2vcpu-4gb-amd': dict(kind='conditional', vcpus=2, memory_mib=4096, nominal_monthly_usd=28.0,
                            display='premium-amd-2vcpu-4g', requires_memory_pressure_from='s-2vcpu-2gb-amd'),
}
GENERATOR_VCPUS = 4
GENERATOR_MEMORY_MIB = 8192

# Frozen workload controls (#60 §3). Any other value is an unsupported substitution.
WORKLOAD_SCHEMA = dict(behavior='strategy', difficulty=1.0, input_hz=30, seed=1,
                       generator_threads=4, bot_id_assignment='round-robin',
                       join_stagger_ms=100, exploration_hold_s=60, confirmation_hold_s=300,
                       readiness_rule='max(60s, nominal_ramp + 30s)', min_configured_players=500)

# Search ceilings (#60 §2).
SEARCH_POLICY = dict(coarse_start=25, coarse_step=25, coarse_max=500, refine_step=5,
                     refine_max_trials=4, confirmations=3, max_trials_per_condition=27)

DEFAULT_RECOVERY_GRACE_S = 300
DEFAULT_TEARDOWN_RESERVE_S = 120

# Per-term timing basis. Terms derived from the accepted contract need no measurement; the
# rest need either calibration evidence or an explicitly declared conservative bound, and a
# capacity session may not run on declared bootstrap/export bounds (#61 Gate C).
CONTRACT_TERMS = ('post_auth_warmup_s',)
TIMING_TERMS = ('create_bootstrap_s', 'readiness_access_s', 'process_reset_s',
                'recorder_finalization_s', 'per_trial_export_s', 'collection_export_s')
CALIBRATED_FOR_CAPACITY = ('create_bootstrap_s', 'readiness_access_s', 'collection_export_s')
TIMING_BASES = ('calibrated', 'declared_conservative')

SHA1_RE = re.compile(r'^[0-9a-f]{40}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
CREDENTIAL_REF_RE = re.compile(r'^(file|env|ref):\S+$')
TOOLCHAIN_RE = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9_]+-[a-z0-9_]+-[a-z0-9_]+(?:-[a-z0-9_]+)*)?$')
CREDENTIAL_FIELDS = ('controller_token_ref', 'watchdog_token_ref')
OBJECT_SECTIONS = ('session', 'session.ownership_tags', 'roles', 'roles.game', 'roles.bot',
                   'ssh_key', 'credentials', 'source', 'source.binary_sha256', 'workload',
                   'telemetry_schema', 'evidence', 'limits', 'timing_basis', 'pricing',
                   'watchdog', 'access_allowlists')
SECRET_PATTERNS = (
    re.compile(r'dop_v1_[0-9a-f]{64}'),          # DigitalOcean personal access token
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'(?i)\bAKIA[0-9A-Z]{16}\b'),
    re.compile(r'(?i)\bbearer\s+[a-z0-9._-]{20,}'),
)


class ManifestError(ValueError):
    """The conditions cannot be frozen. ``reasons`` lists every rejection, not just the first."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__('; '.join(self.reasons))


def canonical_json(value):
    """Deterministic serialization: sorted keys, compact separators, UTF-8, trailing newline."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False) + '\n'


def manifest_sha256(manifest):
    return hashlib.sha256(canonical_json(manifest).encode('utf-8')).hexdigest()


def scan_for_secrets(value, path='$'):
    """Return every location whose string value looks like a credential VALUE."""
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            hits.extend(scan_for_secrets(child, path + '.' + str(key)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            hits.extend(scan_for_secrets(child, path + '[' + str(index) + ']'))
    elif isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                hits.append(path)
                break
    return hits


def _get(mapping, dotted, reasons, required=True):
    node = mapping
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            if required:
                reasons.append('missing ' + dotted)
            return None
        node = node[part]
    return node


def _parse_utc(text, label, reasons):
    try:
        stamp = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        reasons.append(label + ' is not an ISO-8601 timestamp')
        return None
    if stamp.tzinfo is None:
        reasons.append(label + ' must carry a UTC offset')
        return None
    return stamp.astimezone(datetime.timezone.utc)


def _validate_object_sections(value, paths, reasons):
    for path in paths:
        if not isinstance(_get(value, path, reasons), dict):
            reasons.append(path + ' must be a JSON object')


def _preflight_size(preflight, slug):
    for size in preflight.get('sizes', []):
        if size.get('slug') == slug:
            return size
    return None


def _preflight_image(preflight, image_id):
    for image in preflight.get('images', []):
        if image.get('id') == image_id:
            return image
    return None


def _validate_role(role, spec, preflight, reasons):
    """Pin one role's hardware to a preflight size/image record; reject every mismatch."""
    prefix = 'roles.' + role + '.'
    slug = spec.get('size_slug')
    size = _preflight_size(preflight, slug) if slug else None
    if not slug:
        reasons.append('missing ' + prefix + 'size_slug')
    elif size is None:
        reasons.append(prefix + 'size_slug ' + str(slug) + ' is not in the preflight size inventory')
    if spec.get('region') != REGION:
        reasons.append(prefix + 'region must be ' + REGION + ' (public-IP game traffic, one pair per region)')
    if size is not None:
        if REGION not in size.get('regions', []) or not size.get('available', False):
            reasons.append(prefix + 'size ' + slug + ' is not listed available in ' + REGION)
        for field, key in (('vcpus', 'vcpus'), ('memory_mib', 'memory_mib'), ('disk_gib', 'disk_gib')):
            if spec.get(field) != size.get(key):
                reasons.append(prefix + field + ' ' + repr(spec.get(field)) +
                               ' does not match preflight ' + repr(size.get(key)) + ' for ' + slug)
        if spec.get('cpu_class') != size.get('cpu_class'):
            reasons.append(prefix + 'cpu_class ' + repr(spec.get('cpu_class')) +
                           ' does not match preflight ' + repr(size.get('cpu_class')))
        for key in ('price_hourly_usd', 'price_monthly_usd', 'transfer_tib_month'):
            if key not in size:
                reasons.append('preflight size ' + slug + ' lacks ' + key)
    if spec.get('architecture') != 'x64':
        reasons.append(prefix + 'architecture must be the preflight x64 guest architecture')
    image_id = spec.get('image_id')
    if not isinstance(image_id, int) or isinstance(image_id, bool):
        reasons.append(prefix + 'image_id must be the numeric official image ID, not a slug')
    else:
        image = _preflight_image(preflight, image_id)
        if image is None:
            reasons.append(prefix + 'image_id ' + str(image_id) + ' is not in the preflight image inventory')
        else:
            if REGION not in image.get('regions', []):
                reasons.append(prefix + 'image ' + str(image_id) + ' is not available in ' + REGION)
            if image.get('architecture') != 'x64' or not image.get('official', False):
                reasons.append(prefix + 'image ' + str(image_id) + ' is not an official x64 image')
            if size is not None and image.get('min_disk_gib', 10 ** 9) > size.get('disk_gib', 0):
                reasons.append(prefix + 'image ' + str(image_id) + ' needs more disk than ' + slug + ' offers')
    if spec.get('public_route') != 'public-ipv4':
        reasons.append(prefix + 'public_route must be public-ipv4 (parent map condition)')
    if spec.get('private_networking', None) is not False:
        reasons.append(prefix + 'private_networking must be explicitly false (no session VPC)')
    return size


def _validate_source(source, reasons):
    for key in ('benchmark_sha', 'controller_sha', 'adapter_sha'):
        value = source.get(key)
        if not isinstance(value, str) or not SHA1_RE.match(value):
            reasons.append('source.' + key + ' must be a full 40-hex commit SHA, not a moving ref')
    if source.get('clean') is not True:
        reasons.append('source.clean must be true: a dirty or unreviewed tree cannot be benchmarked')
    if source.get('reviewed') is not True:
        reasons.append('source.reviewed must be true: unreviewed source is rejected')
    for key in ('cargo_lock_sha256', 'server_config_sha256', 'content_sha256'):
        if not SHA256_RE.match(str(source.get(key, ''))):
            reasons.append('source.' + key + ' must be a sha256 hex digest')
    toolchain = source.get('rust_toolchain')
    if not isinstance(toolchain, str) or not TOOLCHAIN_RE.fullmatch(toolchain):
        reasons.append('source.rust_toolchain must pin an explicit major.minor.patch version '
                       '(optionally followed by a host triple), not a moving alias')
    if source.get('profile') != 'release':
        reasons.append('source.profile must be release under the accepted build policy')
    if not source.get('target_triple'):
        reasons.append('missing source.target_triple')
    if source.get('locked') is not True:
        reasons.append('source.locked must be true (build with locked dependencies)')
    flags = source.get('build_flags')
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        reasons.append('source.build_flags must be an explicit list of arguments, including features (may be empty)')
    binaries = source.get('binary_sha256') or {}
    for role in ('game', 'bot'):
        if not SHA256_RE.match(str(binaries.get(role, ''))):
            reasons.append('source.binary_sha256.' + role + ' must be a sha256 hex digest')


def _validate_credentials(credentials, reasons):
    for name in set(credentials) - set(CREDENTIAL_FIELDS):
        reasons.append('unsupported credentials field ' + str(name) + ': store supported references only')
    for name in CREDENTIAL_FIELDS:
        value = credentials.get(name)
        if not isinstance(value, str) or not CREDENTIAL_REF_RE.fullmatch(value):
            reasons.append('credentials.' + name + ' must be a file:/env:/ref: reference, never a value')


def _validate_workload(workload, reasons):
    for key, expected in WORKLOAD_SCHEMA.items():
        if key not in workload:
            reasons.append('missing workload.' + key)
        elif workload[key] != expected:
            reasons.append('workload.' + key + ' ' + repr(workload[key]) +
                           ' is not the accepted frozen value ' + repr(expected))
    for key in set(workload) - set(WORKLOAD_SCHEMA):
        reasons.append('workload.' + key + ' is not part of the frozen workload schema')
    configured = workload.get('min_configured_players')
    if isinstance(configured, int) and configured < SEARCH_POLICY['coarse_max']:
        reasons.append('workload.min_configured_players must cover the whole admitted search (>= 500)')


def _validate_timing(timing, kind, reasons):
    """Every term needs a numeric bound and a defensible basis; capacity needs calibration."""
    for term in TIMING_TERMS:
        entry = timing.get(term)
        if not isinstance(entry, dict):
            reasons.append('timing_basis.' + term + ' is absent: no timing basis, workload admission rejected')
            continue
        seconds = entry.get('seconds')
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
            reasons.append('timing_basis.' + term + '.seconds must be a non-negative number')
        basis = entry.get('basis')
        if basis not in TIMING_BASES:
            reasons.append('timing_basis.' + term + '.basis must be one of ' + ', '.join(TIMING_BASES))
        if not entry.get('provenance'):
            reasons.append('timing_basis.' + term + '.provenance must cite the calibration or declaration')
        if basis == 'calibrated' and not SHA256_RE.match(str(entry.get('evidence_sha256', ''))):
            reasons.append('timing_basis.' + term + ' claims calibration without evidence_sha256')
        if kind == 'capacity' and term in CALIBRATED_FOR_CAPACITY and basis != 'calibrated':
            reasons.append('timing_basis.' + term + ' must be calibrated before a capacity session (Gate C)')
    for term in set(timing) - set(TIMING_TERMS) - set(CONTRACT_TERMS):
        reasons.append('timing_basis.' + term + ' is not a recognised term')
    warmup = timing.get('post_auth_warmup_s', {})
    if warmup and warmup.get('seconds') != 2:
        reasons.append('timing_basis.post_auth_warmup_s must stay the accepted 2 seconds')


def _validate_pricing(pricing, reasons):
    for key in ('billing_increment_s', 'billing_minimum_s', 'transfer_overage_usd_per_gib',
                'allowance_hours_per_month'):
        value = pricing.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            reasons.append('pricing.' + key + ' must be a positive number with provenance')
    if pricing.get('prorate_transfer_allowance') not in (True, False):
        reasons.append('pricing.prorate_transfer_allowance must be explicitly true or false')
    if not pricing.get('provenance'):
        reasons.append('pricing.provenance must cite the billing documentation consulted')
    for role in ('game', 'bot'):
        estimate = (pricing.get('estimated_outbound_gib') or {}).get(role)
        if not isinstance(estimate, dict) or not isinstance(estimate.get('gib'), (int, float)) \
                or estimate.get('gib') < 0 or not estimate.get('basis'):
            reasons.append('pricing.estimated_outbound_gib.' + role + ' needs gib and a stated basis')
    management = pricing.get('management_host_monthly_usd')
    if not isinstance(management, (int, float)) or isinstance(management, bool) or management < 0:
        reasons.append('pricing.management_host_monthly_usd must be disclosed (0 if none yet)')


def _validate_limits(limits, reasons):
    for key in ('max_session_duration_s', 'max_estimated_session_usd', 'max_estimated_transfer_gib'):
        value = limits.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            reasons.append('limits.' + key + ' must be an explicit positive number: absent limits are rejected')
    for key, default in (('evidence_recovery_grace_s', DEFAULT_RECOVERY_GRACE_S),
                         ('teardown_reserve_s', DEFAULT_TEARDOWN_RESERVE_S)):
        value = limits.get(key)
        if value is None:
            reasons.append('limits.' + key + ' must be explicit (contract default ' + str(default) + ')')
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            reasons.append('limits.' + key + ' must be a non-negative number')
    cap, grace, reserve = (limits.get(k) for k in ('max_session_duration_s', 'evidence_recovery_grace_s', 'teardown_reserve_s'))
    if all(isinstance(v, (int, float)) for v in (cap, grace, reserve)) and grace + reserve >= cap:
        reasons.append('limits: recovery grace plus teardown reserve leave no time inside the cap')


def _validate_condition(conditions, preflight, reasons):
    game = conditions.get('roles', {}).get('game', {})
    slug = game.get('size_slug')
    accepted = GAME_CONDITIONS.get(slug)
    if accepted is None:
        reasons.append('game size ' + repr(slug) + ' is not an accepted game-host condition')
        return None
    if game.get('vcpus') != accepted['vcpus'] or game.get('memory_mib') != accepted['memory_mib']:
        reasons.append('game vcpus/memory do not match the accepted condition for ' + slug)
    if accepted['kind'] == 'conditional':
        evidence = conditions.get('memory_pressure_evidence')
        if not isinstance(evidence, dict):
            reasons.append('conditional RAM condition ' + slug + ' requires recorded memory_pressure_evidence')
        else:
            if evidence.get('source_condition') != accepted['requires_memory_pressure_from']:
                reasons.append('memory_pressure_evidence.source_condition must be ' +
                               accepted['requires_memory_pressure_from'] + ' for ' + slug)
            kinds = set(evidence.get('indicators') or [])
            memory_kinds = {'oom_kill', 'rss_growth', 'swap_activity', 'page_faults', 'available_memory_low'}
            if not kinds & memory_kinds:
                reasons.append('memory_pressure_evidence.indicators show no memory pressure; high CPU alone '
                               'does not select a RAM tier')
            if not SHA256_RE.match(str(evidence.get('evidence_sha256', ''))):
                reasons.append('memory_pressure_evidence.evidence_sha256 must identify the retained run evidence')
            if not evidence.get('session_id'):
                reasons.append('memory_pressure_evidence.session_id must name the originating session')
        if conditions.get('explicit_conditional_admission') is not True:
            reasons.append('conditional RAM condition ' + slug + ' requires explicit_conditional_admission: true')
    return accepted


def freeze_manifest(conditions, preflight, frozen_at):
    """Validate explicit ``conditions`` against ``preflight`` facts and return (manifest, sha256).

    ``frozen_at`` is the controller's UTC timestamp (injected so fixtures are reproducible).
    Raises ManifestError listing every rejection. The returned manifest contains no derived
    admission results; those live in admission.py and are recomputed from this frozen input.
    """
    reasons = []
    if not isinstance(conditions, dict) or not isinstance(preflight, dict):
        raise ManifestError(['conditions and preflight must be JSON objects'])
    secrets = scan_for_secrets(conditions) + scan_for_secrets(preflight, '$preflight')
    for hit in secrets:
        reasons.append('credential value detected at ' + hit + ': store references only, never a value')

    # Reject malformed containers before any field validator dereferences them. A present
    # null/list must not silently skip the rules enforced for a normal JSON object.
    _validate_object_sections(conditions, OBJECT_SECTIONS, reasons)
    if reasons:
        raise ManifestError(reasons)

    frozen_at = _parse_utc(frozen_at, 'frozen_at', reasons)
    observed_at = _parse_utc(preflight.get('observed_at'), 'preflight.observed_at', reasons)
    if preflight.get('provider') != PROVIDER:
        reasons.append('preflight.provider must be ' + PROVIDER)
    if frozen_at and observed_at and observed_at > frozen_at:
        reasons.append('preflight.observed_at is after frozen_at')

    session_id = _get(conditions, 'session.id', reasons)
    if session_id is not None and not re.match(r'^[a-z0-9][a-z0-9-]{3,63}$', str(session_id)):
        reasons.append('session.id must be a lowercase slug (4-64 chars)')
    kind = _get(conditions, 'session.kind', reasons)
    if kind is not None and kind not in SESSION_KINDS:
        reasons.append('session.kind must be one of ' + ', '.join(SESSION_KINDS))
    _get(conditions, 'session.owner', reasons)
    if _get(conditions, 'session.project_id', reasons) != PROJECT_ID:
        reasons.append('session.project_id must be the existing omega.realm project ' + PROJECT_ID)
    if (preflight.get('project') or {}).get('id') != PROJECT_ID:
        reasons.append('preflight.project.id does not identify the omega.realm project')
    tags = _get(conditions, 'session.ownership_tags', reasons) or {}
    for key in ('session', 'game', 'bot'):
        if not tags.get(key) or (session_id and str(session_id) not in str(tags.get(key))):
            reasons.append('session.ownership_tags.' + key + ' must embed the session id')
    retained = _get(conditions, 'session.retained_resources', reasons)
    if retained is not None and not isinstance(retained, list):
        reasons.append('session.retained_resources must list what teardown preserves')

    roles = _get(conditions, 'roles', reasons) or {}
    sizes = {}
    for role in ('game', 'bot'):
        if role not in roles:
            reasons.append('missing roles.' + role)
            continue
        sizes[role] = _validate_role(role, roles[role], preflight, reasons)
    accepted = _validate_condition(conditions, preflight, reasons) if 'game' in roles else None
    bot = roles.get('bot', {})
    if bot and (bot.get('vcpus') != GENERATOR_VCPUS or bot.get('memory_mib') != GENERATOR_MEMORY_MIB):
        reasons.append('bot host must be the fixed separate 4-vCPU/8-GiB generator')
    if roles.get('game', {}).get('size_slug') and roles.get('game', {}).get('size_slug') == bot.get('size_slug'):
        reasons.append('game and bot roles must not share a size: the generator is a separate fixed host')

    key = _get(conditions, 'ssh_key', reasons) or {}
    registered = {k.get('id'): k for k in preflight.get('ssh_keys', [])}
    if key.get('id') not in registered:
        reasons.append('ssh_key.id is not a registered public key in preflight')
    elif registered[key['id']].get('fingerprint_sha256') != key.get('fingerprint_sha256'):
        reasons.append('ssh_key.fingerprint_sha256 does not match the registered key')
    if key.get('private_key_ref') and not CREDENTIAL_REF_RE.match(str(key.get('private_key_ref'))):
        reasons.append('ssh_key.private_key_ref must be a file:/env:/ref: reference')

    credentials = _get(conditions, 'credentials', reasons) or {}
    _validate_credentials(credentials, reasons)

    _validate_source(conditions['source'], reasons)
    _validate_workload(conditions['workload'], reasons)
    telemetry = _get(conditions, 'telemetry_schema', reasons) or {}
    if not telemetry.get('id') or not SHA256_RE.match(str(telemetry.get('sha256', ''))):
        reasons.append('telemetry_schema needs id and sha256 of the frozen measurement schema')
    evidence = _get(conditions, 'evidence', reasons) or {}
    expected_root = 'loadtest-runs/digitalocean/' + str(session_id)
    if evidence.get('local_root') != expected_root:
        reasons.append('evidence.local_root must be ' + expected_root)
    if kind == 'capacity' and not evidence.get('durable_destination'):
        reasons.append('evidence.durable_destination is required before a capacity session')
    if not isinstance(evidence.get('required_artifacts'), list) or not evidence.get('required_artifacts'):
        reasons.append('evidence.required_artifacts must list the per-role artifacts the exporter checks')

    _validate_limits(conditions['limits'], reasons)
    _validate_timing(conditions['timing_basis'], kind, reasons)
    _validate_pricing(conditions['pricing'], reasons)
    watchdog = _get(conditions, 'watchdog', reasons) or {}
    for name in ('registry_id', 'identity'):
        if not watchdog.get(name):
            reasons.append('watchdog.' + name + ' must identify the trusted registry/watchdog')
    allowlists = _get(conditions, 'access_allowlists', reasons) or {}
    for name in ('ssh_sources', 'operator_udp_sources'):
        if not isinstance(allowlists.get(name), list):
            reasons.append('access_allowlists.' + name + ' must be an explicit list of CIDRs')
        elif any(str(c).endswith('/0') for c in allowlists.get(name)):
            reasons.append('access_allowlists.' + name + ' contains a world-open CIDR')
    if allowlists.get('metrics_public') not in (None, False):
        reasons.append('access_allowlists.metrics_public must be false: metrics stay private')

    account = preflight.get('account') or {}
    if isinstance(account.get('droplet_limit'), int) and isinstance(account.get('droplet_count'), int):
        if account['droplet_limit'] - account['droplet_count'] < 2:
            reasons.append('preflight account quota cannot hold both roles')
    else:
        reasons.append('preflight.account must report droplet_limit and droplet_count')

    if reasons:
        raise ManifestError(reasons)

    quote = {}
    for role, size in sizes.items():
        quote[role] = dict(size_slug=size['slug'], price_hourly_usd=size['price_hourly_usd'],
                           price_monthly_usd=size['price_monthly_usd'],
                           transfer_tib_month=size['transfer_tib_month'])
    manifest = dict(
        schema=MANIFEST_SCHEMA, provider=PROVIDER, frozen_at=frozen_at.isoformat(),
        session=dict(conditions['session'], condition=dict(
            display=accepted['display'], kind=accepted['kind'],
            nominal_monthly_usd=accepted['nominal_monthly_usd'],
            name='do-sgp-' + accepted['display'] + '-public-' + conditions['source']['benchmark_sha'][:12]
                 + '-' + str(session_id))),
        roles=conditions['roles'], ssh_key=conditions['ssh_key'], credentials=conditions['credentials'],
        source=conditions['source'], workload=conditions['workload'],
        search_policy=dict(SEARCH_POLICY), telemetry_schema=conditions['telemetry_schema'],
        evidence=conditions['evidence'], limits=conditions['limits'],
        timing_basis=conditions['timing_basis'], pricing=conditions['pricing'],
        quote=dict(observed_at=observed_at.isoformat(), roles=quote),
        watchdog=conditions['watchdog'], access_allowlists=conditions['access_allowlists'],
        memory_pressure_evidence=conditions.get('memory_pressure_evidence'),
        explicit_conditional_admission=conditions.get('explicit_conditional_admission', False),
        preflight_summary=dict(observed_at=observed_at.isoformat(), project_id=PROJECT_ID,
                               droplet_limit=account['droplet_limit'], droplet_count=account['droplet_count']),
    )
    return manifest, manifest_sha256(manifest)


def verify_manifest(manifest, expected_sha256):
    """Recompute the hash of a loaded manifest; a changed manifest is a changed contract."""
    if not isinstance(manifest, dict):
        raise ManifestError(['manifest must be a JSON object'])
    actual = manifest_sha256(manifest)
    if actual != expected_sha256:
        raise ManifestError(['manifest sha256 ' + actual + ' does not match recorded ' + str(expected_sha256)])
    if manifest.get('schema') != MANIFEST_SCHEMA:
        raise ManifestError(['manifest schema ' + repr(manifest.get('schema')) + ' is not ' + MANIFEST_SCHEMA])
    # Schema /1 files produced by older versions may have bypassed field validation.
    # An intact hash proves integrity, not that the original conditions were supported.
    reasons = []
    _validate_object_sections(manifest, OBJECT_SECTIONS, reasons)
    if reasons:
        raise ManifestError(reasons)
    _validate_source(manifest['source'], reasons)
    _validate_workload(manifest['workload'], reasons)
    _validate_credentials(manifest['credentials'], reasons)
    _validate_limits(manifest['limits'], reasons)
    _validate_timing(manifest['timing_basis'], manifest['session'].get('kind'), reasons)
    _validate_pricing(manifest['pricing'], reasons)
    if reasons:
        raise ManifestError(reasons)
    return actual
