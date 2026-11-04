"""Fresh provider facts, read just before the first mutation and checked against the frozen manifest.

``collect`` only reads. Its result has the same shape as the planner's ``preflight`` input, so the manifest's own
role rules judge it again and a plan, image or key that drifted since the freeze is refused rather than substituted.
A provider listing is not a stock reservation: a create can still fail, and that path cleans up.
"""
import base64
import hashlib

import cleanup_provider
import manifest as manifest_mod
import session_clock

MAX_FACT_AGE_S = 120.0
PROJECT_NAME = 'omega.realm'
AMD_SUFFIX = '-amd'
INTEL_SUFFIX = '-intel'


class PreflightUnavailable(Exception):
    """A required read failed. Missing facts are never treated as good ones."""


def ssh_fingerprint(public_key):
    """``SHA256:...`` as ssh-keygen prints it, computed from the public key text only."""
    fields = str(public_key).split()
    if len(fields) < 2:
        raise ValueError('not an OpenSSH public key')
    digest = hashlib.sha256(base64.b64decode(fields[1])).digest()
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


def _cpu_class(size):
    slug = str(size.get('slug'))
    if slug.endswith(AMD_SUFFIX):
        return 'premium-amd'
    if slug.endswith(INTEL_SUFFIX):
        return 'premium-intel'
    return 'regular'


def _size_fact(size):
    return dict(slug=size.get('slug'), vcpus=size.get('vcpus'), memory_mib=size.get('memory'), disk_gib=size.get('disk'),
                cpu_class=_cpu_class(size), price_hourly_usd=size.get('price_hourly'), price_monthly_usd=size.get('price_monthly'),
                transfer_tib_month=size.get('transfer'), regions=size.get('regions') or [], available=size.get('available') is True)


def _image_fact(image, image_id):
    name = str(image.get('name'))
    return dict(id=image_id, name=name, distribution=image.get('distribution'), architecture='x64' if 'x64' in name else 'unknown',
                official=image.get('public') is True and image.get('type') == 'base' and image.get('status') == 'available',
                min_disk_gib=image.get('min_disk_size'), regions=image.get('regions') or [])


def collect(provider, manifest, wall):
    """Read everything the admission of this session depends on. Raises ``PreflightUnavailable`` on any failure."""
    session = manifest['session']
    tags = session['ownership_tags']
    try:
        project = provider.project(session['project_id'])
        account = provider.account()
        droplet_count = provider.droplet_count()
        regions = provider.regions()
        sizes = provider.sizes()
        images = [dict(_image_fact(image, image_id)) for image_id, image in
                  ((i, provider.image(i)) for i in sorted({manifest['roles'][r]['image_id'] for r in ('game', 'bot')}))
                  if image is not None]
        key = provider.ssh_key(manifest['ssh_key']['id'])
        collisions = dict(droplets=[d['id'] for d in provider.list_droplets_by_tag(tags['session'])],
                          firewalls=[f['id'] for f in provider.list_firewalls_by_name(session['id'] + '-fw')],
                          tags=[t for t in tags.values() if provider.get_tag(t) is not None])
    except cleanup_provider.ProviderError as error:
        raise PreflightUnavailable(type(error).__name__ + ': ' + cleanup_provider.redact(error))
    ssh_keys = []
    if key is not None:
        try:
            fingerprint = ssh_fingerprint(key.get('public_key'))
        except ValueError:
            fingerprint = None      # an unreadable key cannot match the frozen fingerprint
        ssh_keys.append(dict(id=key.get('id'), name=key.get('name'), fingerprint_sha256=fingerprint))
    return dict(provider=manifest_mod.PROVIDER, observed_at=session_clock.iso(wall()),
                project=dict(id=(project or {}).get('id'), name=(project or {}).get('name')),
                account=dict(droplet_limit=(account or {}).get('droplet_limit'), droplet_count=droplet_count,
                             status=(account or {}).get('status')),
                regions=[dict(slug=r.get('slug'), available=r.get('available') is True) for r in regions],
                sizes=[_size_fact(s) for s in sizes], images=images, ssh_keys=ssh_keys, collisions=collisions)


def problems(manifest, facts, health, now, require_watchdog_ack=False):
    """Every reason these facts refuse a first create. Nothing is substituted, adjusted or waited out."""
    reasons = []
    manifest_sha = manifest_mod.manifest_sha256(manifest)
    session = manifest['session']
    age = now - session_clock.parse(facts['observed_at'])
    if age > MAX_FACT_AGE_S or age < 0:
        reasons.append('provider facts are %.0f s old; re-read them' % age)
    if facts['project'].get('id') != session['project_id'] or facts['project'].get('name') != PROJECT_NAME:
        reasons.append('provider project is not the existing ' + PROJECT_NAME + ' project')
    if facts['account'].get('status') != 'active':
        reasons.append('provider account is not active')
    limit, count = facts['account'].get('droplet_limit'), facts['account'].get('droplet_count')
    if not isinstance(limit, int) or not isinstance(count, int) or limit - count < 2:
        reasons.append('account quota cannot hold both roles')
    if not any(r['slug'] == manifest_mod.REGION and r['available'] for r in facts['regions']):
        reasons.append('region ' + manifest_mod.REGION + ' is not available')
    for role in ('game', 'bot'):
        spec = manifest['roles'][role]
        size = manifest_mod._validate_role(role, spec, facts, reasons)
        quoted = manifest['quote']['roles'][role]
        if size is not None and (size.get('price_hourly_usd') != quoted['price_hourly_usd']
                                 or size.get('price_monthly_usd') != quoted['price_monthly_usd']):
            reasons.append('roles.%s price changed since the frozen quote; freeze and admit again' % role)
    key = manifest['ssh_key']
    registered = {k.get('id'): k for k in facts['ssh_keys']}
    if key['id'] not in registered:
        reasons.append('ssh key %s is not registered' % key['id'])
    elif registered[key['id']]['fingerprint_sha256'] != key['fingerprint_sha256']:
        reasons.append('registered ssh key does not have the frozen fingerprint')
    for kind, found in sorted(facts['collisions'].items()):
        if found:
            reasons.append('this session already has provider %s before any create: %s' % (kind, ', '.join(sorted(map(str, found)))))
    registry, watchdog = (health or {}).get('registry') or {}, (health or {}).get('watchdog') or {}
    if registry.get('healthy') is not True:
        reasons.append('registry is not healthy')
    if watchdog.get('healthy') is not True or watchdog.get('identity') != manifest['watchdog']['identity']:
        reasons.append('watchdog is not healthy under its frozen identity')
    if require_watchdog_ack and watchdog.get('acknowledged_manifest_sha256') != manifest_sha:
        reasons.append('watchdog has not acknowledged this manifest')
    return reasons
