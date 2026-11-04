"""Typed evidence that a provider create request has settled, and the only things that count as it.

A client timeout bounds how long this controller waits, not when the provider finishes or shows the
result. Neither elapsed time nor an empty listing therefore says anything about a request whose
outcome is unknown. Such a request stays unresolved, which refuses a retry and a clean closure, until
one of these arrives, each naming the exact request it answers:

  * the resource itself, found by unique tag and name, or read by its exact id;
  * ``CreateRejected``: the provider answered this request with a definitive refusal;
  * ``CreateNotSent``: the grant's holder knows no byte of this request left the process;
  * a ``create_settlement`` receipt from a basis this registry was explicitly told to trust.

No provider basis is trusted by default, so a production registry refuses every receipt until an
adapter documents a real guarantee and names its basis. README.md lists what that adapter must prove.
"""
import dataclasses

import manifest as manifest_mod

SCHEMA_VERSION = 1
KIND = 'create_settlement'
CREATED = 'created'
NOT_CREATED = 'not_created'

OFFLINE_FIXTURE_RECEIPT = 'offline_fixture_receipt'
OFFLINE_FIXTURE_BASES = (OFFLINE_FIXTURE_RECEIPT,)
DEFAULT_TRUSTED_BASES = ()
FIELDS = {'schema_version', 'kind', 'request_ref', 'terminal', 'basis', 'provider_reference', 'resource_id'}


class CreateNotSent(Exception):
    """Raised by a create callback only when no byte of the request left this process."""


class CreateRejected(Exception):
    """Raised by a create callback only for a provider response that definitively refused this request."""


class EvidenceRefused(Exception):
    def __init__(self, code, message):
        super().__init__(code + ': ' + message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class CreateSettlement:
    request_ref: str
    terminal: str
    basis: str
    provider_reference: str
    resource_id: str = None


def request_ref(intent_id, request_number):
    """Names one request, so an answer about an earlier request can never settle a newer one."""
    return intent_id + '#' + str(request_number)


def receipt(ref, terminal, basis, provider_reference, resource_id=None):
    return dict(schema_version=SCHEMA_VERSION, kind=KIND, request_ref=ref, terminal=terminal, basis=basis,
                provider_reference=provider_reference, resource_id=resource_id)


def parse(payload, expected_ref, trusted_bases):
    """Return a ``CreateSettlement``, or raise ``EvidenceRefused``. Anything unexpected is refused."""
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise EvidenceRefused('malformed_settlement', 'a settlement must carry exactly its typed fields')
    if payload['schema_version'] != SCHEMA_VERSION or payload['kind'] != KIND:
        raise EvidenceRefused('malformed_settlement', 'unsupported settlement type or schema')
    hits = manifest_mod.scan_for_secrets(payload)
    if hits:
        raise EvidenceRefused('secret_value_rejected', 'settlement contains a credential value at ' + ', '.join(hits))
    if payload['request_ref'] != expected_ref:
        raise EvidenceRefused('stale_settlement', 'this settlement does not answer the current request')
    if payload['basis'] not in trusted_bases:
        raise EvidenceRefused('untrusted_settlement_basis', 'this registry does not trust that evidence basis')
    reference, terminal, resource_id = payload['provider_reference'], payload['terminal'], payload['resource_id']
    if not isinstance(reference, str) or not reference.strip():
        raise EvidenceRefused('malformed_settlement', 'a settlement must name its provider reference')
    if terminal == CREATED and (not isinstance(resource_id, str) or not resource_id):
        raise EvidenceRefused('malformed_settlement', 'a created settlement must name the exact resource id')
    if terminal == NOT_CREATED and resource_id is not None:
        raise EvidenceRefused('malformed_settlement', 'a not_created settlement cannot name a resource')
    if terminal not in (CREATED, NOT_CREATED):
        raise EvidenceRefused('malformed_settlement', 'a settlement must be terminal')
    return CreateSettlement(expected_ref, terminal, payload['basis'], reference, resource_id)
