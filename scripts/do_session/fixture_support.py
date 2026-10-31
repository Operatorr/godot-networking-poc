"""Shared loaders for the offline fixtures; copies are deep so tests can mutate freely."""
import copy
import json
import pathlib

FIXTURES = pathlib.Path(__file__).with_name('fixtures')
FROZEN_AT = '2026-10-30T12:00:00+00:00'


def load(name):
    return json.loads((FIXTURES / name).read_text())


def conditions():
    return copy.deepcopy(load('conditions_capacity_1vcpu_1g.json'))


def preflight():
    return copy.deepcopy(load('preflight_sgp1_fake.json'))


def health(sha):
    return dict(registry=dict(healthy=True, acknowledged_manifest_sha256=sha),
                watchdog=dict(healthy=True, identity='omega-watchdog@mgmt-1', acknowledged_manifest_sha256=sha))
