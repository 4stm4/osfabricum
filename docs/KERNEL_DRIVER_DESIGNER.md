# OSFabricum — Kernel / Driver Designer

**Milestone:** M33 · **Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

A real kernel and driver designer. Kernel options come from the **selected
kernel source tree's Kconfig** for the **selected arch and version** — never a
flat, global checkbox list. In-tree drivers are enabled as `y`/`m` through
Kconfig; external modules are built against the **exact** kernel build tree,
config, and toolchain.

> Kconfig is a typed dependency graph: symbols have **types** (bool, tristate,
> string, hex, int), **dependencies** (`depends on`), reverse dependencies
> (`select`, `imply`), grouping (`choice`), prompts, and defaults. A symbol can
> be invisible/non-settable because its dependencies are unmet. Treating Kconfig
> as a static global list of booleans is **forbidden** (anti-pattern #15).
> External modules build against a specific kernel build tree via kbuild, so
> they are bound to kernel + config + toolchain.

---

## Why this exists (gap closed)

Audit finding (G-05): today `KernelConfig` references an **opaque `.config`
blob**. There is no symbol index, no dependency awareness, no driver bundles,
and no external-module model. The config hash enters `resolution_hash` only
indirectly via `kernel_id`. This designer makes the kernel configuration a
first-class, validated, explainable model.

---

## Data model

**Kconfig index (per source/version/arch):**

| Table | Purpose |
|-------|---------|
| `kernel_kconfig_indexes` | one index per (kernel source, version, arch) |
| `kernel_option_symbols` | symbol, type (bool/tristate/string/hex/int), prompt, help, default, defined-in file |
| `kernel_option_dependencies` | `depends on` / `select` / `imply` edges between symbols |
| `kernel_option_choices` | `choice` groups and their members |

**Configuration (layered, resolvable, validatable):**

| Table | Purpose |
|-------|---------|
| `kernel_config_presets` | named base configs (defconfig, board defconfig, vendor) |
| `kernel_config_fragments` | reusable fragments (sets of symbol values) |
| `kernel_config_values` | concrete symbol → value entries |
| `kernel_config_layers` | ordered layering of presets + fragments + values |
| `kernel_config_validations` | validation results (unmet deps, type errors, conflicts) |

**Drivers:**

| Table | Purpose |
|-------|---------|
| `driver_bundles` | a named hardware-enablement bundle |
| `driver_bundle_kernel_options` | bundle → required CONFIG symbols (y/m) |
| `driver_bundle_modules` | bundle → in-tree module names |
| `driver_bundle_firmware` | bundle → firmware blobs |
| `driver_bundle_dt_overlays` | bundle → DT overlays (.dtbo) |
| `external_kernel_modules` | out-of-tree module definitions |
| `external_kernel_module_recipes` | how to fetch/build/package them |

---

## Resolution flow

1. **Index** (`kernel.kconfig.index`): parse the kernel source tree's Kconfig
   for the arch → populate symbols, types, dependencies, choices. The index is
   an artifact, keyed by (source hash, version, arch).
2. **Compose** layers: base preset + selected fragments + driver-bundle options
   + user values, in `kernel_config_layers` order.
3. **Resolve** (`kernel.config.resolve`): walk the Kconfig graph — a requested
   `y`/`m` pulls in its `select`/`depends on` closure; unmet `depends on` makes
   a symbol **non-settable** (reported, not silently forced).
4. **Validate** (`kernel.config.validate`): type checks, unmet dependencies,
   `choice` conflicts, tristate misuse → `kernel_config_validations`.
5. **Render** (`kernel.config.render`): emit the final `.config` artifact.
6. **Hash:** the final `.config` content hash enters `resolution_hash`
   **directly** (not just via `kernel_id`).
7. **Build** (`kernel.build`, `kernel.modules.install`): produce Image, modules,
   DTBs, and capture `modules.alias` / `modules.dep` / `modules.builtin`.
8. **External modules** (`external-module.fetch|build|package`): build against
   the exact kernel build tree/config/toolchain; package as `.ofpkg`
   kernel-module packages whose cache key includes kernel release + config hash
   + toolchain hash (see [`PACKAGE_WORKSPACE.md`](PACKAGE_WORKSPACE.md)).

---

## UI

Tabs: **Kernel Source · Base Config · Feature Bundles · Hardware Drivers · Raw
Kconfig Search · Config Fragments · Validation · Final Diff.**

- *Raw Kconfig Search*: search symbols; each result shows type, prompt, current
  value, and its dependency closure ("requires", "selected by", "blocks").
- *Hardware Drivers*: pick driver bundles; the UI shows the CONFIG symbols,
  modules, firmware, and DT overlays each bundle pulls in.
- *Validation*: unmet deps and conflicts shown before any build.
- *Final Diff*: the rendered `.config` vs. the base preset.

## API

`GET /v1/kernels/{id}/options`, `.../options/search?q=`,
`.../options/{symbol}` (type, deps, selected-by, choice);
`POST /v1/kernel-configs/resolve|validate|render|diff|save-preset`;
`POST /v1/driver-bundles`; `POST /v1/external-modules`.

## CLI

`osfabricumctl kernel options search <q>`, `kernel options show <SYMBOL>`,
`kernel-config resolve|validate|render|diff|save-preset`,
`driver-bundle create`, `external-module add|build`.

## Worker jobs

`kernel.kconfig.index`, `kernel.config.resolve`, `kernel.config.validate`,
`kernel.config.render`, `kernel.build`, `kernel.modules.install`,
`external-module.fetch`, `external-module.build`, `external-module.package`,
`driver-bundle.resolve`.

## Artifacts

Kconfig index; final `.config`; config fragments; `modules.alias`,
`modules.dep`, `modules.builtin`; external kernel-module `.ofpkg` packages;
firmware blobs and `.dtbo` overlays attached to bundles.

## Tests

- Kconfig index generated per source/version/arch.
- Symbol search works; dependencies shown.
- **Hidden/non-settable symbols are not treated as normal checkboxes.**
- User-requested options resolved **through** Kconfig (select/depends closure).
- Final `.config` stored as an artifact; **config hash enters
  `resolution_hash`**.
- In-tree drivers enabled as `y`/`m`.
- External modules build against the exact kernel build tree/config/toolchain.
- Firmware and DT overlays attach to a driver bundle.
- `modules.alias` / `modules.dep` / `modules.builtin` captured as artifacts.

## Acceptance criteria

All of the above. A driver bundle is the unit a board/profile selects for
hardware enablement; the resolver expands it into CONFIG symbols + modules +
firmware + overlays, all explainable (M58).
