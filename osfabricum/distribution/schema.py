"""Portable distribution document schema (M26).

A distribution exports to / imports from a self-describing document — the same
shape as ``docs/ROADMAP.md`` §22 (Distribution Definition Format):

.. code-block:: yaml

    apiVersion: osfabricum/v1
    kind: Distribution
    metadata:
      name: my-os
      description: ...
      default_channel: dev
      class: router            # a distribution_class name, or null
    profiles:
      - name: default
        inherits: null         # parent profile name within this distribution
        class: null
        inputs: { ... }        # free-form → profile.inputs_json

Imports are validated, never trusted blindly: :func:`validate_doc` checks the
envelope and profile shape, and the service additionally resolves the ``class``
and ``inherits`` references, failing on anything unknown.
"""

from __future__ import annotations

from typing import Any

API_VERSION = "osfabricum/v1"
KIND = "Distribution"


def validate_doc(data: Any) -> list[str]:
    """Return a list of human-readable problems with *data* (empty == valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["document is not a mapping"]

    if data.get("apiVersion") != API_VERSION:
        errors.append(f"apiVersion must be {API_VERSION!r}")
    if data.get("kind") != KIND:
        errors.append(f"kind must be {KIND!r}")

    meta = data.get("metadata")
    if not isinstance(meta, dict) or not meta.get("name"):
        errors.append("metadata.name is required")

    profiles = data.get("profiles", [])
    if not isinstance(profiles, list):
        errors.append("profiles must be a list")
    else:
        seen: set[str] = set()
        for i, prof in enumerate(profiles):
            if not isinstance(prof, dict) or not prof.get("name"):
                errors.append(f"profiles[{i}].name is required")
                continue
            name = prof["name"]
            if name in seen:
                errors.append(f"duplicate profile name {name!r}")
            seen.add(name)
            inputs = prof.get("inputs")
            if inputs is not None and not isinstance(inputs, dict):
                errors.append(f"profiles[{i}].inputs must be a mapping")

    return errors
