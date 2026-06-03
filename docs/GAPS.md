# OSFabricum — Gap Register

**Revision:** 2026-06
**Source:** Derived from `docs/IMPLEMENTATION_AUDIT.md`.
**Purpose:** A single consolidated list of what is missing or wrong, classified
so the universal roadmap (M24+) can target each gap to a milestone.

Each gap has: an ID, a severity, the milestones it blocks, the evidence (file or
fact), and the milestone that closes it.

Severity scale:

- **S1 — structural**: blocks the universal OS-builder direction; everything
  downstream waits on it.
- **S2 — major**: a whole subsystem is missing or wrong-shaped.
- **S3 — moderate**: a layer (CLI/API/UI/test) is missing for an otherwise
  working feature.
- **S4 — hardening**: works, but a guarantee (security, reproducibility, schema
  integrity) is incomplete.

---

## S1 — Structural gaps

> **Update (2026-06): all three structural gaps are resolved.** G-01 (write
> API) and G-02 (resolver) are fully closed; G-03 (in-process pipeline) is
> resolved at the dispatch level — builds now run as queue-backed jobs on a
> worker — with fine-grained per-package fan-out left as a refinement (M67).
> See per-gap status below.

### G-01 — Write API does not exist
- **Evidence:** Every `apps/api/routes/*` endpoint is read-only except
  `POST /v1/builds/{id}/cancel`. No `POST /v1/builds`, `POST /v1/plan`,
  `POST /v1/prefetch`; no create/update/clone/import/export for any catalog
  entity.
- **Impact:** Nothing can be created or built through the API or UI. The product
  is a read-only catalog + monitor.
- **Blocks:** Distribution Designer, Profile Designer, Build Wizard, all
  designers that persist data.
- **Closed by:** **M26** (distribution write API), **M27** (profile write API),
  **M29** (Plan + Build write API). Auth enforcement on writes: **M14 follow-up
  in M29**.
- **Status: ✅ Resolved.** Write endpoints exist for distributions, profiles,
  plan (with overrides), prefetch, and builds, each with CLI + a designer UI
  page. Auth enforcement on writes remains a hardening follow-up (G-24).

### G-02 — Resolver ignores the profile
- **Evidence:** `osfabricum/resolver/resolver.py:185` computes
  `_merged_inputs = _merge_inputs(profile_chain)` and never reads it. Packages =
  *all* `package_versions` for the arch; toolchain = *first* for the arch;
  kernel = *any* for arch/board.
- **Impact:** Two different profiles of the same distribution on the same arch
  resolve to the **same** package set. Profiles are decorative.
- **Blocks:** Per-profile package selection, package sets/groups, overrides,
  reference distributions (which must differ by data alone).
- **Closed by:** **M27** (profile fields → resolver inputs), **M35** (package
  sets/groups), **M55** (overrides/masking). Dependency topological sort using
  `package_dependencies`: **M35/M57**.
- **Status: ✅ Resolved.** `resolve_plan` consumes the profile's `package_set`
  (and an `inputs.packages` list), plus pinned `kernel`/`toolchain` and M29
  overrides; two profiles on the same arch resolve to different package sets
  (regression-tested). Dependency topological sort remains for M35/M57.

### G-03 — Build pipeline is in-process, not a job graph
- **Evidence:** `osfabricum/pipeline/coordinator.py` `run_pipeline()` calls
  `build_kernel`/`compose_rootfs`/`compose_image` directly and synchronously;
  `BuildJob` rows are bookkeeping; `package.build` is explicitly skipped; there
  is no `osfabricumctl build` verb and no `POST /v1/builds`.
- **Impact:** No parallelism, no worker routing per step, no distributed builds,
  no API/CLI entry to start a build.
- **Blocks:** Build Wizard, distributed build farm, sandboxed builds.
- **Closed by:** **M29** (Build API dispatches a pyjobkit job graph), **M28**
  (wizard → build), **M67** (worker pools), **M68** (isolation).
- **Status: ◑ Resolved at dispatch level (M29).** `POST /v1/builds` creates a
  Build and enqueues a queue-backed `build.run` job that a worker executes via
  the pipeline — off the in-process-only path. `osfabricumctl prefetch`/`build`
  exist. Remaining: fine-grained per-package fan-out (resolve→fetch∥build→
  compose) and per-step worker routing — **M67**.

---

## S2 — Major (subsystem-shaped) gaps

### G-04 — No package taxonomy / layers / groups / sets / variants / feeds / locks
- **Evidence:** `Package.package_type` is a single free string (default
  `"native"`). No tables for kinds, layers, groups, sets, variants, cache
  entries, feeds, locks, promotions.
- **Impact:** System packages and application packages are indistinguishable;
  no reuse of selections across distributions; no feature/variant builds; no
  feed publishing; no runtime package policy.
- **Closed by:** **M35** (workspace + taxonomy + layers/groups/sets + cache),
  **M36** (features/variants), **M37** (feeds), **M38** (runtime policy).

### G-05 — Kernel config is an opaque blob, not a Kconfig model
- **Evidence:** `KernelConfig` references a `config_artifact_id` blob. No Kconfig
  symbol index (types, `depends on`, `select`, `imply`, `choice`, prompts,
  defaults). No driver bundles, no external-module recipes.
- **Impact:** Kernel options cannot be presented or validated; "checkbox"
  configs would be wrong (Kconfig is a typed dependency graph, not a flat list).
  Kernel-module packages have no kernel/config/toolchain binding.
- **Closed by:** **M33** (Kernel/Driver Designer: Kconfig index, fragments,
  validation, driver bundles, external modules, captured `modules.*`).

### G-06 — No image-recipe model (single raw format, hardcoded sizes)
- **Evidence:** `osfabricum/image/composer.py` produces raw `.img` only; sizes
  are hardcoded defaults in the pipeline (`boot_size_mb=4`, `rootfs_size_mb=16`).
- **Impact:** No qcow2/vmdk/iso/squashfs/erofs/btrfs/A-B/recovery/container
  outputs; no per-profile filesystem/layout selection; no size policy.
- **Closed by:** **M34** (Filesystem / Image Recipe Designer).

### G-07 — Branding, graphical shell, applications are not modelled
- **Evidence:** No tables/services for branding profiles/assets, graphical
  stacks, application catalog, desktop integration, themes/fonts.
- **Impact:** Desktop/kiosk/appliance distribution classes are unbuildable
  beyond raw packages; branding is not first-class; "graphical shell" cannot be
  selected as a stack.
- **Closed by:** **M39** (branding), **M40** (graphical shell), **M41**
  (application catalog), **M42** (default apps/desktop integration), **M43**
  (themes/icons/fonts).

### G-08 — Boards are shallow (no BSP depth)
- **Evidence:** `boards` row carries `boot_scheme`, `firmware_required`,
  `metadata_json`. No board revisions, SoC families, device trees, boot schemes,
  flash/test methods, probe profiles as structured entities.
- **Impact:** Hardware targets cannot be described precisely; boot chains and
  initramfs cannot attach to a board model.
- **Closed by:** **M30** (Board/Machine/BSP Designer), **M31** (Boot Chain),
  **M32** (Initramfs).

### G-09 — No secrets/users model
- **Evidence:** No `os_users`/`os_groups`/`secret_variables` tables; secrets
  would live in `config_values` (plain).
- **Impact:** Secrets are not masked or injected safely; no user/group/SSH-key
  generation.
- **Closed by:** **M44** (Users / Groups / Credentials / Secrets Designer).

### G-10 — No network / service-init / security / compliance designers
- **Evidence:** `Service` is a thin row (no ordering, deps, healthchecks); no
  network entities; no security profile; no license/SBOM-gate/vuln entities.
- **Impact:** Router/server/appliance classes cannot express networking,
  service topology, hardening, or compliance gates.
- **Closed by:** **M45** (network), **M46** (service/init/device manager),
  **M47** (security/hardening), **M48** (license/SBOM/vuln/source compliance).

### G-11 — Releases / promotion / OTA / generations missing
- **Evidence:** `Release`/`ReleaseArtifact` models exist but no CLI command, no
  `release.publish` job, no channel promotion flow, no update strategies,
  generations, rollback, recovery images.
- **Impact:** Nothing can be promoted or shipped; GC reference-protection is
  untestable; no A/B or OTA.
- **Closed by:** **M49** (update/OTA/recovery), **M60** (generations/rollback),
  **M61** (attended upgrade), **M69** (public repo/publishing).

### G-12 — Competitive features absent
- **Evidence:** No layers/extensions, override/masking engine, patch queue,
  dependency-graph viewer, explain/why engine, build/profile/release diff,
  lockfile, importers, build-analysis dashboard, size optimizer, boot profiler.
- **Closed by:** **M54** (layers), **M55** (overrides/masking), **M56** (patch
  queue), **M57** (dependency graph), **M58** (explain), **M59** (diff),
  **M62** (lockfile), **M63** (importers), **M64** (build analysis), **M65**
  (size optimizer), **M66** (boot profiler).

---

## S3 — Moderate (missing-layer) gaps

| ID | Gap | Evidence | Closed by |
|----|-----|----------|-----------|
| G-13 | No `osfabricumctl prefetch` from plan | `apps/cli/commands/` has `source.py`, no `prefetch.py` | M28/M29 |
| G-14 | No `osfabricumctl build` verb | `builds` group is read-only (list/show/logs) | M28/M29 |
| G-15 | `builds diff` / `builds reproduce` documented, not implemented | CLI ref §20 vs. `builds.py` | M59 / repro follow-up |
| G-16 | No `releases` CLI / promotion flow | CLI ref §20 vs. no `releases.py` | M49/M69 |
| G-17 | UI is read-only dashboard | `apps/api/static/index.html` (178 lines) | M26–M28 |
| G-18 | No integration/e2e tests | `tests/integration`, `tests/e2e` = `.gitkeep` | M28/M52/M70 |
| G-19 | No explain/why trace on plan items | resolver emits flat lists | M58 |
| G-20 | No SDK / dev-shell export | no module | M50 |
| G-21 | No cache/mirror/offline designer | fetch cache exists; no offline report/mirror priority | M51 |
| G-22 | No hardware probe import | no module | M53 |

---

## S4 — Hardening gaps

| ID | Gap | Evidence | Closed by |
|----|-----|----------|-----------|
| G-23 | Migration `0001` uses `metadata.create_all`, not DDL | `migrations/versions/0001_initial_schema.py` | M24 (CI drift check) / M25 baseline |
| G-24 | Auth not enforced on most API routes | routes lack auth deps | M29 |
| G-25 | Sandbox/PATH isolation are claims, not enforced | builder drivers | M68 |
| G-26 | Secret masking in logs unverified | no secrets model | M44 |
| G-27 | Signing/attestation not exercised e2e | `security/signing.py` | M48/M69 |
| G-28 | Pkg/kernel-module cache keys too weak | no cache-entry model | M35 (key must include arch/libc/toolchain/kernel-release/config hashes) |

---

## Anti-patterns to keep out (regression guard)

These are **forbidden** and should be caught in review/CI:

- `if distribution == "tinywifi" | "netos" | "ocultum"` (or any name) anywhere
  in `osfabricum/` or `apps/`.
- Hardcoded package list, kernel config, or board firmware inside the build
  pipeline.
- Build logic inside the Web UI.
- Package cache key = `name + version + arch` (must also bind source/recipe/
  feature/libc/toolchain/ABI; for kernel-bound packages also kernel-release +
  kernel-config-hash + toolchain-hash).
- Kernel-module cache without `kernel_release + kernel_config_hash +
  toolchain_hash`.
- Secret values in logs.
- Treating Kconfig as a static, flat, global option list.
- Treating branding as "just a wallpaper" or graphical shell as a single
  package checkbox.
- Claiming a documented-only feature is implemented.

Current status: **zero distribution-name branches in code today** — this guard
exists to keep it that way as designers land.
