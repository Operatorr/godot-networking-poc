"""The narrow provider seam the watchdog is allowed to use, and its error taxonomy.

The interface has reads and deletes of exact resources only. It has no create, no project-wide
delete and no way to touch SSH keys, projects or images, so the shared resources a session must
preserve are out of reach by construction. The real DigitalOcean adapter belongs to handoff slice
3; this slice exercises the seam with ``fake_provider.FakeProvider``.

Adapters bound every request with their own timeout, map HTTP 404 to ``None`` on reads and to
acceptance on deletes, and raise exactly one of the errors below. ``get_request_settlement`` is a
read as well, and its default is the fail-closed answer that no evidence exists.
"""
import re

import manifest as manifest_mod

MAX_MESSAGE_CHARS = 300
REDACTIONS = manifest_mod.SECRET_PATTERNS + (
    re.compile(r'(?i)authorization\s*[:=]\s*\S+(?:\s+\S+)?'),
    re.compile(r'(?i)\b(?:token|api[_-]?key|password|secret)\s*[:=]\s*\S+'),
)


class ProviderError(Exception):
    def __init__(self, message, status=None, retry_after_s=None):
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


class ProviderTransient(ProviderError):
    """Timeout, connection failure, 5xx or a locked resource: retry within the burst."""


class ProviderRateLimited(ProviderError):
    """429. ``retry_after_s`` carries the provider's guidance; the hold is token-wide."""


class ProviderAuthError(ProviderError):
    """401/403: operator repair is needed. It is an incident, never a cleanup success."""


def redact(text):
    """Provider text may echo request headers; nothing resembling a credential is ever stored."""
    text = str(text)
    for pattern in REDACTIONS:
        text = pattern.sub('[REDACTED]', text)
    return text[:MAX_MESSAGE_CHARS]


class CleanupProvider:
    """Reads return a dict, or None for an authenticated 404. Deletes return None when accepted."""

    def get_droplet(self, droplet_id):
        """{id, name, tags, status} or None."""
        raise NotImplementedError

    def delete_droplet(self, droplet_id):
        raise NotImplementedError

    def list_droplets_by_tag(self, tag):
        """Every Droplet carrying exactly this tag; adapters follow pagination."""
        raise NotImplementedError

    def get_firewall(self, firewall_id):
        """{id, name, tags, droplet_ids} or None."""
        raise NotImplementedError

    def delete_firewall(self, firewall_id):
        raise NotImplementedError

    def list_firewalls_by_name(self, name):
        raise NotImplementedError

    def get_tag(self, name):
        """{name, resource_count} or None."""
        raise NotImplementedError

    def get_request_settlement(self, request_ref):
        """A ``create_evidence`` receipt for this exact request, or None when there is no such evidence.

        None is the honest default: the request stays unresolved, which refuses a retry and a clean
        closure. An adapter overrides this only for a documented provider guarantee (see README.md).
        """
        return None

    def delete_tag(self, name):
        raise NotImplementedError
