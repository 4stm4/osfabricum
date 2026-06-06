"""Kernel / Driver Designer service (M33).

The heart is :func:`resolve_config`: it loads the Kconfig symbol graph for an
index and resolves a requested ``{symbol: value}`` map through it — type
checking, rejecting hidden symbols, applying ``select`` (forced on) and
``imply`` (soft), and failing requested symbols whose ``depends on`` is unmet.
This is what makes the kernel config a dependency graph, not flat checkboxes.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osfabricum.db.models import (
    DriverBundle,
    DriverBundleDtOverlay,
    DriverBundleFirmware,
    DriverBundleModule,
    DriverBundleOption,
    ExternalKernelModule,
    ExternalKernelModuleRecipe,
    KernelConfigPreset,
    KernelKconfigIndex,
    KernelOptionDependency,
    KernelOptionSymbol,
)
from osfabricum.db.session import sync_session

_ENABLED = ("y", "m")

# dependency edge kind -> the key it is read from in an ingested symbol dict
_DEP_INPUT_KEYS = {"depends": "depends", "select": "selects", "imply": "implies"}


def _type_ok(sym_type: str, value: str) -> bool:
    if sym_type == "bool":
        return value in ("y", "n")
    if sym_type == "tristate":
        return value in ("y", "m", "n")
    if sym_type == "string":
        return True
    if sym_type == "int":
        return value.lstrip("-").isdigit()
    if sym_type == "hex":
        return value.startswith("0x") and all(c in "0123456789abcdefABCDEF" for c in value[2:])
    return False


# ---------------------------------------------------------------------------
# Kconfig index
# ---------------------------------------------------------------------------


def index_kconfig(
    *,
    kernel_id: str,
    arch: str,
    source_ref: str | None = None,
    symbols: list[dict[str, Any]],
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a Kconfig index and ingest *symbols* (with their dependency edges).

    Each symbol dict: ``{name, type, prompt?, help?, default?, depends?[],
    selects?[], implies?[], choice_group?}``. ``depends``/``selects``/``implies``
    are lists of target symbol names.
    """
    with sync_session(db_url) as s:
        index = KernelKconfigIndex(kernel_id=kernel_id, arch=arch, source_ref=source_ref)
        s.add(index)
        s.flush()
        count = 0
        for sym in symbols:
            row = KernelOptionSymbol(
                index_id=index.id,
                name=sym["name"],
                type=sym["type"],
                prompt=sym.get("prompt"),
                help=sym.get("help"),
                default_value=sym.get("default"),
                depends_on=sym.get("depends_on"),
                choice_group=sym.get("choice_group"),
            )
            s.add(row)
            s.flush()
            for kind, input_key in _DEP_INPUT_KEYS.items():
                for target in sym.get(input_key, []):
                    s.add(KernelOptionDependency(symbol_id=row.id, dep_kind=kind, target=target))
            count += 1
        s.commit()
        return {"index_id": index.id, "kernel_id": kernel_id, "arch": arch, "symbol_count": count}


def list_indexes(*, db_url: str | None = None) -> list[dict[str, Any]]:
    """List Kconfig indexes (id, kernel, arch, symbol count)."""
    with sync_session(db_url) as s:
        rows = s.scalars(
            select(KernelKconfigIndex).order_by(KernelKconfigIndex.created_at.desc())
        ).all()
        out: list[dict[str, Any]] = []
        for idx in rows:
            count = len(
                s.scalars(
                    select(KernelOptionSymbol.id).where(KernelOptionSymbol.index_id == idx.id)
                ).all()
            )
            out.append(
                {
                    "id": idx.id,
                    "kernel_id": idx.kernel_id,
                    "arch": idx.arch,
                    "source_ref": idx.source_ref,
                    "symbol_count": count,
                }
            )
        return out


def _index_or_raise(s: Session, index_id: str) -> KernelKconfigIndex:
    idx = s.get(KernelKconfigIndex, index_id)
    if idx is None:
        raise ValueError(f"kconfig index not found: {index_id!r}")
    return idx


def _symbol_dict(sym: KernelOptionSymbol, deps: list[KernelOptionDependency]) -> dict[str, Any]:
    by_kind: dict[str, list[str]] = {"depends": [], "select": [], "imply": []}
    for d in deps:
        by_kind.setdefault(d.dep_kind, []).append(d.target)
    return {
        "name": sym.name,
        "type": sym.type,
        "prompt": sym.prompt,
        "user_selectable": sym.prompt is not None,
        "default": sym.default_value,
        "depends_on": sym.depends_on,
        "depends": by_kind["depends"],
        "selects": by_kind["select"],
        "implies": by_kind["imply"],
    }


def search_options(
    index_id: str, query: str, *, limit: int = 50, db_url: str | None = None
) -> list[dict[str, Any]]:
    q = query.lower()
    with sync_session(db_url) as s:
        _index_or_raise(s, index_id)
        rows = s.scalars(
            select(KernelOptionSymbol)
            .where(KernelOptionSymbol.index_id == index_id)
            .order_by(KernelOptionSymbol.name)
        ).all()
        out = []
        for sym in rows:
            if q in sym.name.lower() or (sym.prompt and q in sym.prompt.lower()):
                out.append(
                    {
                        "name": sym.name,
                        "type": sym.type,
                        "prompt": sym.prompt,
                        "user_selectable": sym.prompt is not None,
                    }
                )
            if len(out) >= limit:
                break
        return out


def get_option(index_id: str, symbol: str, *, db_url: str | None = None) -> dict[str, Any]:
    with sync_session(db_url) as s:
        _index_or_raise(s, index_id)
        sym = s.scalar(
            select(KernelOptionSymbol).where(
                KernelOptionSymbol.index_id == index_id, KernelOptionSymbol.name == symbol
            )
        )
        if sym is None:
            raise ValueError(f"unknown symbol: {symbol!r}")
        deps = s.scalars(
            select(KernelOptionDependency).where(KernelOptionDependency.symbol_id == sym.id)
        ).all()
        result = _symbol_dict(sym, list(deps))
        # reverse: who selects this symbol
        selected_by = s.scalars(
            select(KernelOptionSymbol.name)
            .join(KernelOptionDependency, KernelOptionDependency.symbol_id == KernelOptionSymbol.id)
            .where(
                KernelOptionSymbol.index_id == index_id,
                KernelOptionDependency.dep_kind == "select",
                KernelOptionDependency.target == symbol,
            )
        ).all()
        result["selected_by"] = list(selected_by)
        return result


# ---------------------------------------------------------------------------
# Resolver (the heart, G-05)
# ---------------------------------------------------------------------------


def resolve_config(
    index_id: str, requested: dict[str, str], *, db_url: str | None = None
) -> dict[str, Any]:
    """Resolve *requested* options through the Kconfig graph."""
    with sync_session(db_url) as s:
        _index_or_raise(s, index_id)
        symbols = {
            sym.name: sym
            for sym in s.scalars(
                select(KernelOptionSymbol).where(KernelOptionSymbol.index_id == index_id)
            ).all()
        }
        id_to_name = {sym.id: sym.name for sym in symbols.values()}
        edges = s.scalars(
            select(KernelOptionDependency).where(
                KernelOptionDependency.symbol_id.in_(list(id_to_name))
            )
        ).all()

    depmap: dict[str, dict[str, list[str]]] = {
        name: {"depends": [], "select": [], "imply": []} for name in symbols
    }
    for e in edges:
        depmap[id_to_name[e.symbol_id]].setdefault(e.dep_kind, []).append(e.target)

    errors: list[str] = []
    warnings: list[str] = []
    resolved: dict[str, str] = {}
    explain: dict[str, str] = {}

    # 1. validate and apply the user-requested values
    for name, value in requested.items():
        sym = symbols.get(name)
        if sym is None:
            errors.append(f"unknown symbol: {name}")
            continue
        if sym.prompt is None:
            errors.append(f"{name} is not user-selectable (hidden; set via select/default only)")
            continue
        if not _type_ok(sym.type, value):
            errors.append(f"invalid value {value!r} for {name} (type {sym.type})")
            continue
        resolved[name] = value
        explain[name] = "manual"

    # 2. apply select (forced on, ignores the target's own deps) to a fixpoint
    changed = True
    while changed:
        changed = False
        for name, value in list(resolved.items()):
            if value in _ENABLED:
                for tgt in depmap.get(name, {}).get("select", []):
                    if tgt in symbols and resolved.get(tgt) not in _ENABLED:
                        resolved[tgt] = "y"
                        explain.setdefault(tgt, f"selected by {name}")
                        changed = True

    # 3. apply imply (soft: enable only if the target is otherwise unset)
    for name, value in list(resolved.items()):
        if value in _ENABLED:
            for tgt in depmap.get(name, {}).get("imply", []):
                if tgt in symbols and tgt not in resolved:
                    resolved[tgt] = "y"
                    explain.setdefault(tgt, f"implied by {name}")

    # 4. a requested-on symbol whose 'depends on' is still unmet cannot be set
    for name in list(resolved):
        if resolved[name] in _ENABLED:
            unmet = [
                t
                for t in depmap.get(name, {}).get("depends", [])
                if resolved.get(t) not in _ENABLED
            ]
            if unmet and explain.get(name) == "manual":
                errors.append(f"{name} cannot be enabled: depends on {', '.join(unmet)}")
            elif unmet:
                warnings.append(f"{name} depends on {', '.join(unmet)} (not enabled)")

    return {
        "index_id": index_id,
        "resolved": resolved,
        "explain": explain,
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
    }


def validate_config(
    index_id: str, requested: dict[str, str], *, db_url: str | None = None
) -> dict[str, Any]:
    r = resolve_config(index_id, requested, db_url=db_url)
    return {"valid": r["valid"], "errors": r["errors"], "warnings": r["warnings"]}


def render_config(
    index_id: str, resolved: dict[str, str], *, db_url: str | None = None
) -> dict[str, Any]:
    """Render a resolved option map to ``.config`` text + a content hash."""
    with sync_session(db_url) as s:
        _index_or_raise(s, index_id)
        types = {
            sym.name: sym.type
            for sym in s.scalars(
                select(KernelOptionSymbol).where(KernelOptionSymbol.index_id == index_id)
            ).all()
        }
    lines: list[str] = []
    for name in sorted(resolved):
        value = resolved[name]
        kind = types.get(name, "bool")
        if kind in ("bool", "tristate"):
            lines.append(
                f"CONFIG_{name}={value}" if value in _ENABLED else f"# CONFIG_{name} is not set"
            )
        elif kind == "string":
            lines.append(f'CONFIG_{name}="{value}"')
        else:  # int / hex
            lines.append(f"CONFIG_{name}={value}")
    text = ("\n".join(lines) + "\n") if lines else ""
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"content": text, "config_hash": digest, "lines": len(lines)}


def diff_config(a: str, b: str) -> dict[str, Any]:
    """Diff two ``.config`` texts by CONFIG line."""

    def parse(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("CONFIG_") and "=" in line:
                k, _, v = line.partition("=")
                out[k] = v
            elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
                out[line[2 : -len(" is not set")]] = "n"
        return out

    pa, pb = parse(a), parse(b)
    added = {k: pb[k] for k in pb.keys() - pa.keys()}
    removed = {k: pa[k] for k in pa.keys() - pb.keys()}
    changed = {k: {"a": pa[k], "b": pb[k]} for k in pa.keys() & pb.keys() if pa[k] != pb[k]}
    return {"added": added, "removed": removed, "changed": changed}


def save_preset(
    name: str, content: str, *, kernel_id: str | None = None, db_url: str | None = None
) -> dict[str, Any]:
    digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    with sync_session(db_url) as s:
        preset = KernelConfigPreset(
            name=name, kernel_id=kernel_id, content=content, config_hash=digest
        )
        s.add(preset)
        s.commit()
        return {"id": preset.id, "name": name, "config_hash": digest}


# ---------------------------------------------------------------------------
# Driver bundles
# ---------------------------------------------------------------------------


def create_driver_bundle(
    name: str,
    *,
    kernel_id: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.scalar(select(DriverBundle).where(DriverBundle.name == name)) is not None:
            raise ValueError(f"driver bundle already exists: {name!r}")
        bundle = DriverBundle(name=name, kernel_id=kernel_id, description=description)
        s.add(bundle)
        s.commit()
        return {"id": bundle.id, "name": name}


def _bundle_or_raise(s: Session, bundle_id: str) -> DriverBundle:
    bundle = s.get(DriverBundle, bundle_id)
    if bundle is None:
        raise ValueError(f"driver bundle not found: {bundle_id!r}")
    return bundle


def add_bundle_option(
    bundle_id: str, symbol: str, value: str = "y", *, db_url: str | None = None
) -> dict[str, Any]:
    if value not in _ENABLED:
        raise ValueError("driver-bundle option value must be 'y' or 'm'")
    with sync_session(db_url) as s:
        _bundle_or_raise(s, bundle_id)
        s.add(DriverBundleOption(bundle_id=bundle_id, symbol=symbol, value=value))
        s.commit()
    return {"bundle_id": bundle_id, "symbol": symbol, "value": value}


def add_bundle_module(
    bundle_id: str, module_name: str, *, db_url: str | None = None
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        _bundle_or_raise(s, bundle_id)
        s.add(DriverBundleModule(bundle_id=bundle_id, module_name=module_name))
        s.commit()
    return {"bundle_id": bundle_id, "module": module_name}


def add_bundle_firmware(
    bundle_id: str, filename: str, *, db_url: str | None = None
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        _bundle_or_raise(s, bundle_id)
        s.add(DriverBundleFirmware(bundle_id=bundle_id, filename=filename))
        s.commit()
    return {"bundle_id": bundle_id, "firmware": filename}


def add_bundle_dt_overlay(
    bundle_id: str, overlay_name: str, *, db_url: str | None = None
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        _bundle_or_raise(s, bundle_id)
        s.add(DriverBundleDtOverlay(bundle_id=bundle_id, overlay_name=overlay_name))
        s.commit()
    return {"bundle_id": bundle_id, "dt_overlay": overlay_name}


def list_driver_bundles(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {"id": b.id, "name": b.name, "description": b.description}
            for b in s.scalars(select(DriverBundle).order_by(DriverBundle.name)).all()
        ]


def resolve_driver_bundle(bundle_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Expand a bundle into its kernel options, modules, firmware and DT overlays."""
    with sync_session(db_url) as s:
        bundle = _bundle_or_raise(s, bundle_id)
        options = {
            o.symbol: o.value
            for o in s.scalars(
                select(DriverBundleOption).where(DriverBundleOption.bundle_id == bundle_id)
            ).all()
        }
        modules = [
            m.module_name
            for m in s.scalars(
                select(DriverBundleModule).where(DriverBundleModule.bundle_id == bundle_id)
            ).all()
        ]
        firmware = [
            f.filename
            for f in s.scalars(
                select(DriverBundleFirmware).where(DriverBundleFirmware.bundle_id == bundle_id)
            ).all()
        ]
        overlays = [
            d.overlay_name
            for d in s.scalars(
                select(DriverBundleDtOverlay).where(DriverBundleDtOverlay.bundle_id == bundle_id)
            ).all()
        ]
        return {
            "bundle": bundle.name,
            "options": options,
            "modules": modules,
            "firmware": firmware,
            "dt_overlays": overlays,
        }


# ---------------------------------------------------------------------------
# External (out-of-tree) kernel modules
# ---------------------------------------------------------------------------


def create_external_module(
    name: str,
    *,
    source_uri: str | None = None,
    source_ref: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.scalar(select(ExternalKernelModule).where(ExternalKernelModule.name == name)):
            raise ValueError(f"external module already exists: {name!r}")
        mod = ExternalKernelModule(name=name, source_uri=source_uri, source_ref=source_ref)
        s.add(mod)
        s.commit()
        return {"id": mod.id, "name": name}


def add_external_module_recipe(
    module_id: str,
    kernel_id: str,
    *,
    build_system: str = "kbuild",
    steps: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.get(ExternalKernelModule, module_id) is None:
            raise ValueError(f"external module not found: {module_id!r}")
        recipe = ExternalKernelModuleRecipe(
            module_id=module_id, kernel_id=kernel_id, build_system=build_system, steps_json=steps
        )
        s.add(recipe)
        s.commit()
        return {"id": recipe.id, "module_id": module_id, "kernel_id": kernel_id}


def list_external_modules(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {"id": m.id, "name": m.name, "source_uri": m.source_uri, "source_ref": m.source_ref}
            for m in s.scalars(
                select(ExternalKernelModule).order_by(ExternalKernelModule.name)
            ).all()
        ]
