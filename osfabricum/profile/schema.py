"""Portable profile document schema (M27).

.. code-block:: yaml

    apiVersion: osfabricum/v1
    kind: Profile
    metadata:
      distribution: my-os
      name: default
    spec:
      inherits: base          # parent profile name (same distribution)
      class: router           # any reference below is by name, or null
      board: rpi-zero-2w
      kernel: linux-rpi
      toolchain: aarch64-linux-musl
      package_set: core
      boot_scheme: u-boot
      image_recipe: sdcard
      branding_profile: my-brand
      graphical_profile: kiosk
      network_profile: ap
      security_profile: hardened
      update_strategy: ab
      validation_profile: smoke
      inputs: { ... }         # free-form → profile.inputs_json

Imports are validated and every reference is resolved to an existing entity;
unknown references fail the import.
"""

from __future__ import annotations

from typing import Any

API_VERSION = "osfabricum/v1"
KIND = "Profile"

# spec field -> profile column it sets. Reference fields are resolved by name.
REF_FIELDS: dict[str, str] = {
    "class": "class_id",
    "board": "board_id",
    "kernel": "kernel_id",
    "toolchain": "toolchain_id",
    "boot_scheme": "boot_scheme_id",
    "package_set": "package_set_id",
    "image_recipe": "image_recipe_id",
    "branding_profile": "branding_profile_id",
    "graphical_profile": "graphical_profile_id",
    "network_profile": "network_profile_id",
    "security_profile": "security_profile_id",
    "update_strategy": "update_strategy_id",
    "validation_profile": "validation_profile_id",
}


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
    if not isinstance(meta, dict) or not meta.get("distribution") or not meta.get("name"):
        errors.append("metadata.distribution and metadata.name are required")
    spec = data.get("spec", {})
    if not isinstance(spec, dict):
        errors.append("spec must be a mapping")
    elif spec.get("inputs") is not None and not isinstance(spec.get("inputs"), dict):
        errors.append("spec.inputs must be a mapping")
    return errors
