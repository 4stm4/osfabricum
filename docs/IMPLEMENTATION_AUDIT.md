# OSFabricum — Implementation Audit (M0–M23)

**Audit revision:** 2026-06
**Scope:** Verifies the actual state of milestones M0–M23 against `docs/ROADMAP.md`.
**Method:** Code was inspected directly (DB models, migrations, services, CLI,
API routes, worker, tests, artifact store). A milestone is **not** considered
done because a file or a table exists. Each milestone is checked as a vertical:
DB model → migration → service/usecase → API → CLI → UI → worker job →
tests → artifact produced → end-to-end → absence of hardcoded
distribution-specific logic.

This document is the source of truth for `docs/GAPS.md` and
`docs/NEXT_ACTIONS.md`, and is referenced by `docs/ROADMAP.md` →
*Current Implementation Status*.

---

## Status vocabulary

| Status | Meaning |
|--------|---------|
| `done` | Implemented across the relevant vertical, with tests, produces the expected artifact. |
| `partial` | Core exists but one or more layers (API write / CLI / UI / job graph) are missing. |
| `missing` | Planned in ROADMAP, not present in code. |
| `implemented-but-not-tested` | Code path exists, no automated test covers it. |
| `documented-only` | Described in ROADMAP/CLI reference, no code behind it. |
| `needs-redesign` | Implemented for one shape, incompatible with the universal OS-builder model. |
| `needs-hardening` | Works, but security/correctness/reproducibility guarantees are incomplete. |

---

## Executive summary

**The core is genuinely distribution-agnostic.** A full-tree grep for
`tinywifi|netos|ocultum` across `osfabricum/` and `apps/` returns **one** hit —
a docstring example in `osfabricum/rootfs/builder.py`. There are **no**
`if distribution == ...` branches, no hardcoded package lists, and no hardcoded
kernel configs in the build pipeline. This is the single most important
architectural fact: the data-driven foundation that the universal roadmap
(M24+) builds on is real and not blocked by special-case code.

**Three structural gaps dominate everything downstream:**

1. **The write API does not exist.** Every `apps/api/routes/*` endpoint is
   read-only except `POST /v1/builds/{id}/cancel`. There is **no**
   `POST /v1/builds`, no `POST /v1/plan`, no `POST /v1/prefetch`, and no
   create/update endpoints for distributions, profiles, boards, packages, etc.
   The API is a read-only catalog + build monitor. (Blocks M26–M29.)

2. **The resolver ignores the profile.** `resolve_plan()` computes
   `_merged_inputs` from the profile inheritance chain and then **discards it**
   (`osfabricum/resolver/resolver.py:185`). Packages are selected as *"all
   `package_versions` for the arch"*, toolchain as *"any toolchain for the
   arch"*, kernel as *"any kernel for the arch/board"*. There is no notion of a
   profile declaring a package set. (Blocks M25, M27, M35.)

3. **The pipeline runs in-process, not as a pyjobkit job graph.**
   `run_pipeline()` calls `compose_rootfs`/`compose_image`/`build_kernel`
   directly and synchronously. `BuildJob` rows are bookkeeping, not dispatched
   jobs. `package.build` is explicitly skipped. There is no single
   `osfabricumctl build` command and no API to start a build. (Blocks M28, M29,
   M67.)

**Secondary gaps:** UI is one read-only dashboard (no creation, no wizard);
`integration/` and `e2e/` test directories contain only `.gitkeep`; releases
have models but no CLI/job; package taxonomy and kernel Kconfig modelling are
opaque (single `package_type` string, kernel config is a blob, not a symbol
index). Alembic migration `0001` uses `Base.metadata.create_all` rather than
explicit DDL, so migrations are not true incremental schema operations.

---

## Per-milestone audit

Legend for vertical cells: `✓` present · `~` partial · `✗` missing · `n/a` not
applicable to this milestone.

### M0 — Scope

| Dimension | State |
|---|---|
| Planned in ROADMAP | Define product boundaries; distributions are data, not code paths. |
| Implemented in code | `docs/ROADMAP.md` exists; vision/concepts/architecture documented. |
| DB / API / CLI / UI / Worker / Artifact | n/a (a scope document). |
| Tests | n/a |
| **Status** | **`done`** (with wording debt) |
| Gaps | Vision text is TinyWifi-centric ("tinywifi ← first native MVP"; section *First Native Target: TinyWifi*). The principle "distributions are records, not code paths" is stated but the document elevates one distribution to MVP centre. |
| Next action | M24: add *Current Implementation Status*; reframe TinyWifi/NetOS/Ocultum as reference distributions (Phase 5). |

### M1 — Application Skeleton

| Dimension | State |
|---|---|
| Implemented | `apps/cli` (Typer, 16 command groups), `apps/api` (FastAPI `app.py`), `apps/worker` (`main.py`). `pyproject.toml` defines entry points. `.github/` CI present. SQLite dev DB (`osfabricum-dev.db`) works without config. |
| DB ✓ · API ✓ · CLI ✓ · UI ✓ · Worker ✓ · Artifact n/a · Tests ✓ (`test_cli.py`, `test_api.py`) | |
| **Status** | **`done`** |
| Gaps | None material. |
| Next action | None. |

### M2 — Database Registry

| Dimension | State |
|---|---|
| Implemented | `osfabricum/db/models.py` (28 mapped classes). `migrations/versions/0001–0005`. `alembic.ini`. Seed YAML in `catalog/seed/` (architectures, boards, distributions, toolchains, kernels, firmware, sources). `osfabricumctl catalog list …`. |
| DB ✓ · CLI ✓ · Tests ✓ (`test_catalog.py`) | |
| **Status** | **`done` / `needs-hardening`** |
| Gaps | Migration `0001_initial_schema.py` calls `Base.metadata.create_all(bind)` instead of explicit `op.create_table(...)`. Migrations `0003–0005` add columns incrementally, so the chain is *partly* declarative and *partly* a metadata dump — schema drift between models and migrations is not caught. No autogenerate baseline. |
| Next action | Replace `0001` with explicit DDL or add a migration-vs-model drift check in CI. |

### M3 — Artifact Store

| Dimension | State |
|---|---|
| Implemented | `osfabricum/store/{ingest,verify,layout,gc,retention}.py`. `Artifact` model with `blob_sha256`, `store_key` (unique), `retention_class`, `pinned`, `input_hash` (indexed). Content-addressed blobs + refs. `osfabricumctl store/artifacts …`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ (`test_store.py`) | |
| **Status** | **`done`** |
| Gaps | Single-node filesystem store only; no remote/S3 backend (post-MVP, acknowledged). |
| Next action | None for M0–M23. Remote store tracked under M51/M67. |

### M4 — Job Runtime / pyjobkit

| Dimension | State |
|---|---|
| Implemented | `osfabricum/queue/{backend,worker}.py`; real pyjobkit integration (commit `fb78e30`). `migration 0002` adds `job_tasks`. `BuildJob` model. Tests `test_queue.py`, `test_worker.py`. |
| DB ✓ · CLI ~ · Worker ✓ · Tests ✓ | |
| **Status** | **`partial`** |
| Gaps | The job runtime is **not used by the build pipeline** (M18). `run_pipeline()` executes steps in-process; `BuildJob` rows are records, not pyjobkit-dispatched jobs. No job-graph fan-out/fan-in. No `/internal/queue` dashboard. `/metrics` queue-depth-per-kind not verified. |
| Next action | M29/M67: dispatch pipeline steps as real pyjobkit jobs with dependency edges. |

### M5 — Worker Capability Model

| Dimension | State |
|---|---|
| Implemented | `Worker` model (`kinds_json`, `tags_json`, `capabilities_json`). Tag-based routing (commit `4c32efa`). `osfabricumctl workers list`. `GET /v1/workers`, `GET /v1/workers/{hostname}`. |
| DB ✓ · API ✓ (read) · CLI ✓ · Tests ✓ (`test_worker.py`) | |
| **Status** | **`done`** (lifecycle `needs-hardening`) |
| Gaps | Self-registration on startup and stale-worker (`> 3× lease_ttl` → offline) transitions exist as design; offline-marking is not strongly covered by tests. No worker pools (M67). |
| Next action | Add offline-transition test; defer pools to M67. |

### M6 — Toolchain Model

| Dimension | State |
|---|---|
| Implemented | `osfabricum/toolchain/{fetch,handler}.py`. `Toolchain` + `ToolchainArtifact` models. `osfabricumctl toolchain add/fetch/verify/list`. sha256 verify after fetch. Tests `test_toolchain.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | None material. ABI/triple hashing for cache keys is not surfaced (needed for M35 package cache). |
| Next action | Expose toolchain hash for package cache keys (M35). |

### M7 — Source Fetcher / Prefetch

| Dimension | State |
|---|---|
| Implemented | `osfabricum/fetcher/{http,git,fetch,handler}.py`. `Source` model. sha256 verify, cache hit on duplicate. `osfabricumctl source …`. Tests `test_fetcher.py`. |
| DB ✓ · CLI ~ · Worker ✓ · Tests ✓ | |
| **Status** | **`partial`** |
| Gaps | The fetch primitive is `done`. **Prefetch orchestration is missing**: there is no `osfabricumctl prefetch <dist>/<profile>` command that derives sources from a build plan and enqueues `source.fetch` per package, and no `POST /v1/prefetch`. Offline-readiness report not implemented (M51). |
| Next action | M28/M29/M51: prefetch-from-plan command + API + offline report. |

### M8 — Build System / Recipes

| Dimension | State |
|---|---|
| Implemented | `osfabricum/builder/drivers/{cargo,make,cmake,meson,autotools,custom}.py` + `base.py`; `recipe.py`, `context.py`. `BuildRecipe` model. `osfabricumctl package build`. Tests `test_builder.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done`** (`needs-hardening` on isolation) |
| Gaps | PATH restriction / "fail if undeclared host tool invoked" / sandbox isolation are design claims, not enforced (M68). Recipe hash exists but feature/variant hashing is absent (M36). |
| Next action | M36 (variants), M68 (sandbox policy). |

### M9 — Package Model / .ofpkg

| Dimension | State |
|---|---|
| Implemented | `osfabricum/packaging/{builder,installer}.py`. `.ofpkg` spec in `docs/formats/`. `Package`/`PackageVersion`/`PackageDependency` models. Tamper rejection, checksum + manifest validation, CycloneDX SBOM. Tests `test_packaging.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done` / `needs-redesign`** |
| Gaps | `Package.package_type` is a single free string (default `"native"`). **No package taxonomy** (system/runtime/library/service/desktop/application/theme/branding/kernel-module/firmware/…), **no layers, groups, sets, variants, feeds, locks**. System packages and application packages are not separated. Kernel-module packages have no kernel/config/toolchain binding in their identity. |
| Next action | M35/M36/M37/M38: package workspace, taxonomy, variants, feeds, runtime policy. |

### M10 — Kernel Model

| Dimension | State |
|---|---|
| Implemented | `osfabricum/kernel/{build,handler}.py`. `Kernel` + `KernelConfig` models. `migration 0003` (`kernel_metadata_json`). Builds Image + modules + DTBs; cross-compiles aarch64. `osfabricumctl kernel build/list/show`. Tests `test_kernel.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done` (build)** / **`needs-redesign` (config model)** |
| Gaps | The kernel **config is an opaque artifact blob**, not a Kconfig symbol model. There is no Kconfig index (symbols, types, `depends on`, `select`, `imply`, `choice`, defaults, prompts), so kernel options cannot be presented as anything but free text/blobs. No driver bundles, no in-tree driver y/m model, no external module recipes (built against a specific kernel build tree). Config hash enters `resolution_hash` only indirectly via `kernel_id`. |
| Next action | M33: full Kernel/Driver Designer (Kconfig index, fragments, validation, driver bundles, external modules). |

### M11 — Config / Overlay / Firmware Model

| Dimension | State |
|---|---|
| Implemented | `osfabricum/config/{renderer,overlay,firstboot}.py`; `osfabricum/firmware/fetch.py`. `ConfigTemplate`/`ConfigValue`/`Overlay`/`Script`/`Service`/`FirmwareBlob` models. `migration 0004` (`firmware_metadata_json`). Deterministic rendering. `osfabricumctl firmware …`. Tests `test_config.py`, `test_firmware.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | `Service` is a thin row (name, init_system, unit artifact, enabled flag) — no ordering, dependencies, healthchecks (M46). Firmware is board-scoped only; not yet linked to driver bundles (M33). |
| Next action | M46 (service/init designer), M33 (firmware↔driver bundle link). |

### M12 — Resolver / Build Plan

| Dimension | State |
|---|---|
| Implemented | `osfabricum/resolver/{resolver,plan}.py`. Deterministic `resolution_hash`. Profile inheritance chain walk + cycle detection. `osfabricumctl plan`. `GET /v1/plan`. Tests `test_resolver.py`. |
| DB ✓ · API ~ (read) · CLI ✓ · Tests ✓ | |
| **Status** | **`partial` / `needs-redesign`** |
| Gaps | **The merged profile inputs are computed and discarded** (`resolver.py:185` `_merged_inputs = _merge_inputs(...)`, never read). Consequences: packages = *all* `package_versions` for the arch (not profile-declared); toolchain = *first* toolchain for the arch; kernel = *any* kernel for arch/board. No package-set, package-group, override, or layer resolution. No dependency topological sort (the `package_dependencies` table is not consulted). No explain/why trace. `GET /v1/plan` is read-only; `POST /v1/plan` (with overrides) is missing. |
| Next action | M27/M29/M35/M55/M58: wire profile inputs → package sets; add overrides, dependency sort, explain trace, write Plan API. |

### M13 — Reproducibility Model

| Dimension | State |
|---|---|
| Implemented | `osfabricum/repro/{chain,env}.py`. `SOURCE_DATE_EPOCH`, deterministic tar flags, build-env hash chain. `resolution_hash` stored on `builds`. Tests `test_repro.py`. |
| DB ✓ · CLI ~ · Tests ✓ | |
| **Status** | **`partial`** |
| Gaps | `osfabricumctl builds diff <a> <b>` and `osfabricumctl builds reproduce <id>` are in the CLI reference but **not implemented** — the `builds` command group is read-only (`list`/`show`/`logs`). Build-environment spec artifact-per-build not verified end-to-end. |
| Next action | M59 (build diff), plus a `builds reproduce` command. |

### M14 — Security Baseline

| Dimension | State |
|---|---|
| Implemented | `osfabricum/security/{auth,policy,sbom,signing}.py`. sha256 verify on ingest. CycloneDX SBOM generation. Cosign signing module. Tests `test_security.py`. |
| DB ~ · API ~ · CLI ~ · Worker ~ · Tests ✓ | |
| **Status** | **`partial` / `needs-hardening`** |
| Gaps | Auth/role enforcement exists as a module but is **not uniformly enforced** across API routes (most routes are unauthenticated read). Per-worker tokens, secret masking in logs, and signing-key isolation are designed but not verified by tests. SBOM signing and attestation bundle storage not exercised end-to-end. No secrets model (secrets are not separated from config values — M44). |
| Next action | M44 (secrets designer), enforce auth on write API (M29), M47/M48 (hardening/compliance gates). |

### M15 — Base RootFS Builder

| Dimension | State |
|---|---|
| Implemented | `osfabricum/rootfs/{builder,etcfiles,initsystem,layout}.py`. busybox/musl base, `/etc` skeleton, init choice. `osfabricumctl rootfs build-base`. Tests `test_rootfs.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | Single base shape (busybox/musl). glibc/systemd base and alternative device managers are model-supported but not exercised (M46). |
| Next action | M46 (init/device-manager matrix). |

### M16 — RootFS Composer

| Dimension | State |
|---|---|
| Implemented | `osfabricum/composer/{rootfs,packages,services}.py`. Installs `.ofpkg` into staging, overlays, services, first-boot tasks. `osfabricumctl compose rootfs`. Tests `test_composer.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | Install order does not use a resolved dependency graph (resolver gap, M12). Branding/graphical/application layers not yet distinct inputs (M39–M43). |
| Next action | M35 (ordered install), M39–M43 (UI/branding layers). |

### M17 — Partition Layout / Image Composer

| Dimension | State |
|---|---|
| Implemented | `osfabricum/image/{composer,bootfiles,fat16,mbr}.py`. `PartitionLayout` model. Raw image, FAT boot + ext-like root, boot files. `osfabricumctl compose image`. Tests `test_image.py`. |
| DB ✓ · CLI ✓ · Artifact ✓ · Tests ✓ | |
| **Status** | **`done` (raw)** / **`partial` (formats)** |
| Gaps | Only raw `.img` output. No qcow2/vmdk/iso/squashfs/erofs/btrfs/A-B/recovery/container-rootfs. Image sizes are hardcoded defaults in the pipeline (`boot_size_mb=4`, `rootfs_size_mb=16` in `pipeline/coordinator.py`). Image recipe is not a first-class, selectable entity. |
| Next action | M34: Filesystem / Image Recipe Designer (multi-format, A/B, size policies). |

### M18 — Build Pipeline

| Dimension | State |
|---|---|
| Implemented | `osfabricum/pipeline/{coordinator,log,record}.py`. `run_pipeline()` resolves → (kernel) → base rootfs → compose rootfs → image. Records `BuildJob`/`BuildEvent`/`BuildLog`. Tests `test_pipeline.py`. |
| DB ✓ · API ✗ · CLI ✗ · Worker ~ · Artifact ✓ · Tests ✓ | |
| **Status** | **`partial`** |
| Gaps | (1) **In-process, synchronous** — not a pyjobkit job graph; no parallel fan-out, no worker routing per step. (2) `package.build` is **explicitly skipped** (pre-built packages only). (3) **No `osfabricumctl build` command** — the end-to-end orchestration is library-only (`run_pipeline`), reachable from tests, not from a single CLI verb or API. (4) No `POST /v1/builds`. |
| Next action | M28/M29: Build Wizard + Plan/Build write API + real job graph; expose `osfabricumctl build`. |

### M19 — Build History / Logs / Events

| Dimension | State |
|---|---|
| Implemented | `osfabricum/pipeline/{log,record}.py`. `BuildEvent`/`BuildLog`/`BuildJob` models. `osfabricumctl builds list/show/logs`. `GET /v1/builds`, `/{id}`, `/{id}/events`, `/{id}/events/stream` (SSE), `/{id}/logs`. Tests `test_build_history.py`. |
| DB ✓ · API ✓ (read) · CLI ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | Read side complete. Filtering by all documented dimensions (date ranges, cursors) partially covered. |
| Next action | None blocking. Build-analysis views tracked under M64. |

### M20 — API + Web UI v1

| Dimension | State |
|---|---|
| Implemented | `apps/api/routes/{catalog,builds,artifacts_api,workers_api,plan_api}.py`. `apps/api/static/index.html` (read-only dashboard, 178 lines, fetches `/v1/builds`, `/v1/artifacts`, `/v1/catalog/*`, `/v1/workers`, `/metrics`). Tests `test_api.py`, `test_api_v1.py`. |
| DB ✓ · API ~ · CLI n/a · UI ~ · Tests ✓ | |
| **Status** | **`partial`** (this is the largest UI/API gap) |
| Gaps | **API is read-only** except `POST /v1/builds/{id}/cancel`. Missing: `POST /v1/builds`, `POST /v1/plan`, `POST /v1/prefetch`, and all catalog write/create/clone/import/export endpoints. **UI cannot create anything** — no "create build", no prefetch trigger, no wizard, no designers (the ROADMAP claimed "Web UI: create build job" and "trigger prefetch" — both absent). Auth not enforced on most endpoints. |
| Next action | M26–M29 (write API + designers), M28 (wizard UI). |

### M21 — Flash Utility

| Dimension | State |
|---|---|
| Implemented | `osfabricum/flasher/{flash,device}.py`. Device allowlist, sha256 verify before/after write, full dd. `osfabricumctl flash …`. Tests `test_flash.py`. |
| DB ✓ · CLI ✓ · Worker ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | No `cap:flash` worker-pool gating beyond capability flags (M67). |
| Next action | M67 (hardware-lab/flash worker pools). |

### M22 — Test Runner

| Dimension | State |
|---|---|
| Implemented | `osfabricum/testkit/{qemu,runner,suites}.py`. QEMU boot test, SSH/service healthchecks, manifest checks. `osfabricumctl imagetest …`. Tests `test_testkit.py`. |
| DB ~ · CLI ✓ · Worker ✓ · Artifact ✓ · Tests ✓ (unit) | |
| **Status** | **`done` (unit)** / **`implemented-but-not-tested` (real QEMU)** |
| Gaps | QEMU paths are unit-tested with mocks; there is **no integration/e2e harness** (`tests/integration/`, `tests/e2e/` contain only `.gitkeep`). Validation profiles are not first-class entities (M52). "Failing test blocks promotion" not wired (no release/promotion engine). |
| Next action | M52 (validation designer), real e2e under M28/M70. |

### M23 — Store GC / Retention

| Dimension | State |
|---|---|
| Implemented | `osfabricum/store/{gc,retention}.py`. Retention classes on `Artifact` (`release`/`staging`/`cache-hot`/…), `pinned` honoured. `osfabricumctl store gc/stats`. Tests `test_store_gc.py`. |
| DB ✓ · CLI ✓ · Worker ✓ · Tests ✓ | |
| **Status** | **`done`** |
| Gaps | "GC never deletes artifacts referenced by a release record" cannot be fully exercised because the release/promotion engine is not wired (models exist, no CLI/job). |
| Next action | Wire releases (Phase 4/Phase 5 publishing, M69) so GC reference-protection is testable. |

---

## Cross-cutting findings

| Area | State | Note |
|---|---|---|
| Distribution-agnostic core | **`done`** ✓ | No `if distribution == …`, no hardcoded package/kernel/firmware lists in pipeline. 1 docstring mention only. |
| Write API surface | **`missing`** | Read-only catalog + build monitor + `cancel`. No create/update/clone/import/export anywhere. |
| Resolver ↔ profile wiring | **`needs-redesign`** | Profile inputs computed then discarded; resolution is arch-driven, not profile-driven. |
| Build orchestration as jobs | **`partial`** | In-process; pyjobkit not used for build steps; no `osfabricumctl build`. |
| Releases / promotion | **`documented-only`** | `Release`/`ReleaseArtifact` models exist; no CLI command, no `release.publish` job, no channel promotion flow in code. |
| Package taxonomy / layers | **`missing`** | One `package_type` string; no layers/groups/sets/variants/feeds/locks. |
| Kernel Kconfig model | **`missing`** | Config is an opaque blob; no symbol index/dependencies/validation. |
| Integration / e2e tests | **`missing`** | Only `.gitkeep`; all 27 test files are unit tests. |
| Branding / graphical / applications | **`missing`** | Not modelled as subsystems. |
| Boards / BSP depth | **`partial`** | `boards` row has `boot_scheme`+`firmware_required`+`metadata_json`; no revisions, SoC families, device trees, flash/test methods as structured entities. |
| Secrets | **`missing`** | Secrets not separated from `config_values`; no masking model verified. |

---

## What this means for the roadmap

- **Do not restart M0–M23.** The primitives (store, fetch, toolchain, recipes,
  `.ofpkg`, kernel build, rootfs, image, flash, test, GC, history) are real and
  mostly `done`.
- **The next work is the *write* and *model* layer**, not more build
  primitives: a universal data model (M25), designers that produce that data
  (M26–M56), a resolver that actually consumes the profile (M27/M35/M55), a
  Plan/Build write API and job graph (M28/M29), and the competitive features
  (layers, overrides, explain, diff, lockfiles, importers, analysis — M54–M66).
- **Reference distributions (TinyWifi/NetOS/Ocultum)** become validation
  profiles in Phase 5 — test data over the universal model, never code paths.

See `docs/GAPS.md` for the consolidated gap list and `docs/NEXT_ACTIONS.md` for
the prioritized action queue.
