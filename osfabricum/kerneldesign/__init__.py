"""Kernel / Driver Designer (M33).

Models Kconfig as a typed symbol dependency graph and resolves a requested set
of options through it — honouring symbol types, ``depends on``, ``select`` and
hidden (non-prompt) symbols — instead of treating Kconfig as a flat list of
checkboxes (the forbidden anti-pattern, closes G-05). Also models driver
bundles and out-of-tree kernel modules built against a specific kernel tree.

The Kconfig *parser* (reading a real kernel source tree into the index) and the
external-module *build execution* are follow-ons; this module owns the data
model, the resolver/validator/renderer, and the driver/external-module catalog.
"""

from __future__ import annotations

from osfabricum.kerneldesign.service import (
    add_bundle_dt_overlay,
    add_bundle_firmware,
    add_bundle_module,
    add_bundle_option,
    add_external_module_recipe,
    create_driver_bundle,
    create_external_module,
    diff_config,
    get_option,
    index_kconfig,
    list_driver_bundles,
    list_external_modules,
    list_indexes,
    render_config,
    resolve_config,
    resolve_driver_bundle,
    save_preset,
    search_options,
    validate_config,
)

__all__ = [
    "add_bundle_dt_overlay",
    "add_bundle_firmware",
    "add_bundle_module",
    "add_bundle_option",
    "add_external_module_recipe",
    "create_driver_bundle",
    "create_external_module",
    "diff_config",
    "get_option",
    "index_kconfig",
    "list_driver_bundles",
    "list_external_modules",
    "list_indexes",
    "render_config",
    "resolve_config",
    "resolve_driver_bundle",
    "save_preset",
    "search_options",
    "validate_config",
]
