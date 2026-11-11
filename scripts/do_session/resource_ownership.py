"""Whose resource is this? One answer, shared by the watchdog before a delete and the controller before any change.

Pure functions over a frozen manifest and one provider record, so provisioning can never certify or operate on what
cleanup would later refuse to delete. A problem here is reported and preserved, never repaired: nothing strips a
protected tag or a retained id to make a resource deletable.
"""
PROTECTED_TAGS = ('omega-management',)


def resource_key(kind, provider_id):
    return kind + ':' + str(provider_id)


def retained_problems(manifest, key):
    if key in (manifest['session'].get('retained_resources') or []):
        return ['resource is listed as retained by the manifest']
    return []


def droplet_problems(manifest, key, droplet, protected_tags=PROTECTED_TAGS):
    """Exact session tag, role tag and expected name; no protected tag; not a retained id."""
    session = manifest['session']
    tags = session['ownership_tags']
    problems = retained_problems(manifest, key)
    actual = set(droplet.get('tags') or [])
    if tags['session'] not in actual:
        problems.append('droplet does not carry the unique session tag')
    protected = actual.intersection(protected_tags)
    if protected:
        problems.append('droplet carries a protected management tag: ' + ', '.join(sorted(protected)))
    role = {session['id'] + '-' + role: role for role in ('game', 'bot')}.get(droplet.get('name'))
    if role is None:
        problems.append('droplet name is not an expected session name')
    elif tags[role] not in actual:
        problems.append('droplet does not carry its role tag')
    return problems


def firewall_problems(manifest, key, firewall, owned_droplet_ids):
    """What cleanup needs in order to delete. A controller replacing rules must hold the stricter exact-target check."""
    session = manifest['session']
    tags = session['ownership_tags']
    problems = retained_problems(manifest, key)
    if firewall.get('name') != session['id'] + '-fw':
        problems.append('firewall name is not the expected session name')
    if not set(firewall.get('tags') or []).issubset({tags['session'], tags['game'], tags['bot']}):
        problems.append('firewall targets tags outside this session')
    if not {str(d) for d in (firewall.get('droplet_ids') or [])}.issubset(owned_droplet_ids):
        problems.append('firewall targets Droplets this session does not own')
    return problems


def tag_problems(manifest, key, provider_id, tag):
    problems = retained_problems(manifest, key)
    if tag.get('name') != provider_id or provider_id not in manifest['session']['ownership_tags'].values():
        problems.append('tag is not an ownership tag of this session')
    if tag.get('resource_count'):
        problems.append('tag still labels %s resource(s) after owned Droplets are gone' % tag.get('resource_count'))
    return problems
