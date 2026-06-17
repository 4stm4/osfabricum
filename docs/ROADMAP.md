# OSFabricum Roadmap

**Project:** `4stm4/osfabricum`  
**Roadmap revision:** 2025

> Build system for Linux-based operating systems, firmware, and bootable images.
> Maintained by 4STM4.

---

## 1. Vision

OSFabricum is a platform for building, composing, signing, and releasing
Linux-based operating systems and firmware images.

It is NOT:
- a Buildroot wrapper
- a NetOS wrapper
- a web UI for a legacy build system

It IS:
- an independent OS build factory
- driven by a database registry of distributions, boards, packages, kernels
- capable of producing bootable images for embedded and desktop targets
- designed for reproducible, verifiable, signed artifacts

Key architectural decision:

  No distribution is a backend.
  Every distribution is a set of records managed by OSFabricum.

  OSFabricum builds many classes of OS from one data-driven core:
  embedded, router, server, desktop, kiosk, appliance,
  mobile/handheld, recovery, firmware, container-host, hypervisor-host.

  Reference distributions (validation profiles, not architecture):
    - tinywifi   ← router/embedded reference distribution
    - netos      ← infrastructure/SDN reference distribution
    - ocultum    ← mobile/handheld reference distribution

All distributions — reference or product — are records in the database,
never code paths. The core MUST stay distribution-agnostic: no build
pipeline may contain `if distribution == tinywifi/netos/ocultum`
special branches. See **Current Implementation Status** below and
`docs/IMPLEMENTATION_AUDIT.md` for the verified state of the core.

---

## 2. Core Concepts

### Distribution
A named OS product. Defined entirely by data in the registry.
Examples: tinywifi, netos, ocultum.

### Profile
A named configuration of a distribution.
Examples: tinywifi/default, netos/nervum, ocultum/minimal.
Profiles can inherit from other profiles.

### Board
A supported hardware or virtual target.
Examples: rpi-zero-2w, qemu-x86_64, rpi5.

### Kernel
A versioned, board-specific Linux kernel build with config and patches.

### Toolchain
A cross-compilation toolchain with target arch, libc, and version.
Examples: aarch64-linux-musl, arm-linux-gnueabihf.

### Package
A first-party or third-party software component.
Output: a versioned .ofpkg artifact.

### .ofpkg
The native OSFabricum package format.

  nanodhcp-0.1.0-aarch64.ofpkg
  ├── manifest.json
  ├── files.tar.zst
  ├── checksums.sha256
  ├── scripts/
  │   ├── preinst
  │   ├── postinst
  │   ├── prerm
  │   └── postrm
  └── sbom.json

### Build Plan
The output of the Resolver for a given distribution/profile/board triple.
Contains: arch, toolchain, kernel, packages, firmware, overlays,
scripts, partition layout, missing artifacts, required jobs,
resolution_hash.

### Resolution Hash
A deterministic hash of all inputs to a build plan.
Same inputs → same hash → same expected output.

### Artifact Store
Immutable content-addressed blob storage.
Every artifact has a sha256, store_key, and metadata record.

### Worker
An independent process that claims and executes jobs.
Workers declare capabilities and arch. They do not depend on the UI.

---

## 3. Architecture

┌─────────────────────────────────────────────────────────┐
│                        Clients                          │
│          osfabricumctl  /  Web UI  /  CI                │
└────────────────────┬────────────────────────────────────┘
│ HTTP / SSE
┌────────────────────▼────────────────────────────────────┐
│                   Orchestrator API                       │
│               FastAPI + Pydantic v2                      │
└──────┬─────────────────────────┬───────────────────────┘
│                         │
┌──────▼──────┐         ┌────────▼────────┐
│  PostgreSQL  │         │   pyjobkit      │
│  Registry   │         │   Job Queue     │
│  + History  │         │   SQL backend   │
└──────┬──────┘         └────────┬────────┘
│                         │
┌──────▼─────────────────────────▼────────┐
│              Workers                     │
│  source.fetch / kernel.build /           │
│  package.build / rootfs.compose /        │
│  image.compose / image.test /            │
│  image.flash / store.gc                  │
└──────────────────┬───────────────────────┘
│
┌──────────────────▼───────────────────────┐
│           Artifact Store                  │
│   /var/lib/osfabricum/store/              │
│   content-addressed blobs + refs          │
└───────────────────────────────────────────┘

Boundaries:
- Web UI is a client. It builds nothing.
- Workers are independent processes. They do not share state with the UI.
- The queue is owned by pyjobkit. OSFabricum does not reimplement it.
- The store owns all immutable outputs. Worker disks are disposable.
- The database owns all metadata. Files own only payloads.

---

## 4. Database Model

### Core Registry Tables

| Table                 | Key columns                                                        |
|-----------------------|--------------------------------------------------------------------|
| architectures         | id, name (aarch64, x86_64, riscv64)                               |
| boards                | id, name, arch_id, boot_scheme, firmware_required, metadata_json  |
| distributions         | id, name, description, default_channel, metadata_json             |
| profiles              | id, distribution_id, name, inherits_id, inputs_json               |
| kernels               | id, name, version, arch_id, board_id, source_uri, source_ref      |
| --- | --- |
| kernel_configs        | id, kernel_id, board_id, config_artifact_id                       |
| toolchains            | id, name, arch_id, libc, version, source_type, metadata_json      |
| --- | --- |
| toolchain_artifacts   | id, toolchain_id, artifact_id, verified_at                        |
| packages              | id, name, namespace, package_type, metadata_json                  |
| package_versions      | id, package_id, version, arch_id, recipe_id, artifact_id, status  |
| --- | --- |
| package_dependencies  | src_version_id, dep_name, constraint_expr, dep_type               |
| build_recipes         | id, package_version_id, build_system, steps_json, env_json        |
| sources               | id, uri, source_type, ref, expected_hash, metadata_json           |
| --- | --- |
| overlays              | id, name, distribution_id, profile_id, board_id, artifact_id     |
| scripts               | id, name, hook, content_artifact_id, metadata_json                |
| services              | id, name, init_system, unit_artifact_id, enabled_by_default       |
| firmware_blobs        | id, board_id, filename, artifact_id, required, placement          |
| partition_layouts     | id, name, board_id, layout_json                                   |
| config_templates      | id, name, template_artifact_id, schema_json                       |
| config_values         | id, template_id, profile_id, board_id, values_json               |

### Build Runtime Tables

| Table          | Key columns                                                              |
|----------------|--------------------------------------------------------------------------|
| builds         | id, distribution_id, profile_id, board_id, resolution_hash, status      |
| --- | --- |
| build_jobs     | id, build_id, pyjobkit_job_id, step_kind, attempt, status               |
| --- | --- |
| build_events   | id, build_id, job_id, ts, event_type, payload_json                      |
| --- | --- |
| build_logs     | id, build_id, job_id, ts, stream, line_no, message                      |
| --- | --- |
| artifacts      | id, kind, name, version, arch, store_key, blob_sha256, size_bytes,      |
|                | media_type, retention_class, pinned, producer_build_id, metadata_json   |
| --- | --- |
| artifact_relations    | parent_id, child_id, relation_type                               |
| artifact_attestations | id, artifact_id, attestation_type, bundle_artifact_id           |
| workers        | id, hostname, enabled, kinds_json, tags_json, capabilities_json         |
| releases       | id, distribution_id, version, channel, status, published_at             |
| --- | --- |
| release_artifacts     | release_id, artifact_id, role                                    |

### Resolver Output (not a table — a computed struct)

```json
{
  "distribution": "tinywifi",
  "profile": "default",
  "board": "rpi-zero-2w",
  "arch": "aarch64",
  "resolution_hash": "sha256:...",
  "toolchain": { "id": "...", "artifact_id": "..." },
  "kernel": { "id": "...", "artifact_id": "..." },
  "packages": [ { "name": "nanodhcp", "version": "0.1.0", "status": "built" } ],
  "firmware": [ { "filename": "start4.elf", "artifact_id": "..." } ],
  "overlays": [],
  "scripts": [],
  "partition_layout": { "id": "...", "layout_json": {} },
  "missing_artifacts": [],
  "required_jobs": ["package.build:nanodhcp", "rootfs.compose", "image.compose"]
}

## 5. Artifact Store
### Layout

/var/lib/osfabricum/
├── store/
│   ├── blobs/
│   │   └── sha256/ab/cd/<full-sha256>
│   └── refs/
│       ├── packages/<name>/<version>/<arch>/<name>-<version>-<arch>.ofpkg
│       ├── kernels/<name>/<version>/<arch>/Image
│       ├── rootfs/<distro>/<profile>/<board>/<build_id>/rootfs.tar.zst
│       ├── images/<distro>/<profile>/<board>/<version>/<name>.img.zst
│       ├── sbom/<subject-sha256>/<format>.json
│       ├── attestations/<subject-sha256>/<issuer>.json
│       └── releases/<distro>/<channel>/<version>/manifest.json
├── cache/
│   ├── sources/
│   ├── toolchains/
│   ├── ccache/
│   └── package-build/
└── work/
    └── tmp/    ← ephemeral, disposable

### Artifact Metadata (key fields)
| Field | Required | Notes |
| --- | --- | --- |
| blob_sha256 | yes | Canonical identity. Verified on ingest. |
| store_key | yes | Human-readable ref path |
| kind | yes | package, kernel, rootfs, image, sbom, ... |
| retention_class | yes | release / staging / cache-hot / failed-run |
| --- | --- | --- |
| pinned | yes | Prevents GC |
| producer_build_id | no | Traceability |
### Retention Classes
| Class | Default retention | GC behaviour |
| --- | --- | --- |
| release | indefinite | explicit delete only |
| promoted | indefinite | explicit demotion required |
| staging | 90 days | delete if unpinned |
| cache-hot | 30 days | LRU within quota |
| cache-cold | 7–14 days | aggressive GC |
| failed-run | 14–30 days | logs kept longer than blobs |
## 6. Job Runtime
Built on pyjobkit + PostgreSQL.

### Job Kinds
| Job kind | Tags | Retry policy |
| --- | --- | --- |
| resolve.plan | distro:, arch: | fixed, 3 attempts |
| source.fetch | arch:* | exponential |
| --- | --- | --- |
| toolchain.fetch | arch:* | exponential |
| kernel.build | cap:kernel, arch:* | manual / infra only |
| package.build | cap:package, arch:* | exponential for fetch |
| rootfs.compose | cap:compose, arch:* | fixed |
| image.compose | cap:image, board:* | fixed |
| image.test | cap:qemu, arch:* | fixed |
| image.flash | cap:flash, device:* | no auto-retry |
| artifact.sign | cap:sign | fixed |
| artifact.attest | cap:sign | fixed |
| store.gc | cap:gc | fixed |
| release.publish | channel:* | fixed |
### Job Chain for a Full Build

resolve.plan
    ↓
source.fetch          (parallel, all packages + kernel)
toolchain.fetch       (parallel)
    ↓
kernel.build          (if not cached)
package.build × N     (parallel, per arch)
    ↓
rootfs.compose
    ↓
image.compose
    ↓
image.test            (optional, QEMU)
artifact.sign
artifact.attest
    ↓
release.publish       (on promotion)

### API Surface
| Method + Path | Purpose |
| --- | --- |
| POST /v1/builds | Create a build |
| GET /v1/builds/{id} | Build summary |
| GET /v1/builds/{id}/events | SSE event stream |
| GET /v1/builds/{id}/logs | Paged logs |
| POST /v1/builds/{id}/cancel | Cancel |
| POST /v1/prefetch | Prefetch sources / toolchains |
| --- | --- |
| GET /v1/plan | Resolve plan without building |
| GET /v1/artifacts | Search artifacts |
| GET /v1/artifacts/{id} | Artifact metadata + refs |
| GET /v1/catalog/distributions | Browse distributions |
| GET /v1/catalog/boards | Browse boards |
| GET /v1/catalog/packages | Browse packages |
| GET /v1/workers | Worker inventory |
| GET /healthz | Liveness |
| GET /readyz | Readiness |
| GET /metrics | Prometheus metrics |
## 7. Worker Model
Workers are independent processes.
They claim jobs by kind and tags.
They never depend on the UI or API process being alive.

### Worker Fields
| Field | Example |
| --- | --- |
| worker_id | worker-aarch64-01 |
| kinds[] | ["kernel.build", "package.build"] |
| tags[] | ["arch:aarch64", "cap:qemu"] |
| capabilities_json | {"qemu": true, "flash": false} |
| max_concurrency | 2 |
| lease_ttl_s | 60 |
| heartbeat_period_s | 10 |
| work_root | /var/lib/osfabricum/work |
| store_mount | /var/lib/osfabricum/store |
### Example Worker Profiles

worker-rpi5:
  arch: aarch64
  kinds: [kernel.build, package.build, rootfs.compose, image.compose]
  capabilities:
    build_kernel: true
    build_package: true
    flash_sd: true
    qemu: false

worker-x86:
  arch: x86_64
  kinds: [package.build, rootfs.compose, image.compose, image.test]
  capabilities:
    qemu: true
    flash_sd: false

## Current Implementation Status

The full vertical audit of M0–M23 (DB → migration → service → API → CLI → UI →
worker job → tests → artifact → end-to-end → distribution-agnosticism) lives in
**[`docs/IMPLEMENTATION_AUDIT.md`](IMPLEMENTATION_AUDIT.md)**. The consolidated
gap register is **[`docs/GAPS.md`](GAPS.md)** and the prioritized work queue is
**[`docs/NEXT_ACTIONS.md`](NEXT_ACTIONS.md)**.

Summary of M0–M23 (status vocabulary: `done` / `partial` / `missing` /
`implemented-but-not-tested` / `documented-only` / `needs-redesign` /
`needs-hardening`):

| Milestone | Status | Headline gap (if any) |
|-----------|--------|------------------------|
| M0 Scope | `done` | wording was TinyWifi-centric (fixed here) |
| M1 Application Skeleton | `done` | — |
| M2 Database Registry | `done` / `needs-hardening` | migration `0001` uses `metadata.create_all`, not DDL |
| M3 Artifact Store | `done` | single-node FS store only |
| M4 Job Runtime | `partial` | pyjobkit not used by the build pipeline |
| M5 Worker Capability Model | `done` | offline-transition under-tested |
| M6 Toolchain Model | `done` | toolchain hash not exposed for cache keys |
| M7 Source Fetcher | `partial` | no prefetch-from-plan command/API |
| M8 Build System / Recipes | `done` / `needs-hardening` | PATH/sandbox isolation not enforced |
| M9 Package Model / .ofpkg | `done` / `needs-redesign` | no taxonomy/layers/groups/sets/variants |
| M10 Kernel Model | `done` (build) / `needs-redesign` (config) | kernel config is an opaque blob, not Kconfig |
| M11 Config / Overlay / Firmware | `done` | services are thin rows (no order/health) |
| M12 Resolver / Build Plan | `partial` / `needs-redesign` | **profile inputs computed then discarded** |
| M13 Reproducibility Model | `partial` | `builds diff` / `reproduce` not implemented |
| M14 Security Baseline | `partial` / `needs-hardening` | auth not enforced; no secrets model |
| M15 Base RootFS Builder | `done` | single busybox/musl base shape |
| M16 RootFS Composer | `done` | install order not dependency-resolved |
| M17 Partition / Image Composer | `done` (raw) / `partial` (formats) | raw `.img` only; hardcoded sizes |
| M18 Build Pipeline | `partial` | **in-process, not a job graph; no `build` verb/API** |
| M19 Build History / Logs | `done` | read side complete |
| M20 API + Web UI v1 | `partial` | **read-only API + read-only dashboard** |
| M21 Flash Utility | `done` | — |
| M22 Test Runner | `done` (unit) / not e2e | `integration/`, `e2e/` are empty |
| M23 Store GC / Retention | `done` | release reference-protection untestable (no releases) |

**Verified core property:** zero `if distribution == …` branches and zero
hardcoded package/kernel/firmware lists in `osfabricum/` and `apps/` (one
docstring mention only). The data-driven foundation is real.

**Three structural gaps gate everything from M24 onward** (see GAPS.md
G-01/G-02/G-03):

1. **Write API does not exist** — the API is a read-only catalog + build
   monitor (`POST /v1/builds/{id}/cancel` is the only mutation).
2. **The resolver ignores the profile** — `resolve_plan()` discards merged
   profile inputs; selection is arch-driven, so profiles are decorative.
3. **The pipeline runs in-process** — not a pyjobkit job graph; no
   `osfabricumctl build`; `package.build` is skipped.

M24–M29 close these three before the designer milestones (M30+) land.

> **Progress (2026-06).** M24–M70 have landed. **All three structural gaps are
> resolved.** Phase 4 (Universal OS Builder Expansion) is complete — every
> milestone from M24 through M69 shipped its full vertical (DB + migration +
> service + API + CLI + UI + tests). Key milestones: M26 (Distribution Write
> API), M27 (Profile Designer), M29 (Plan/Build API), M30–M43 (hardware/boot/
> branding/app designers), M44–M53 (users/network/security/compliance/SDK/
> mirror/probe), M54–M56 (layers/overrides/patches), M57–M60 (graph/explain/
> diff/generations), M61–M69 (upgrade/lockfile/importers/analysis/sizeopt/
> boot-profiler/worker-pools/isolation/repository). Gaps closed: G-01 through
> G-22, G-25. M70 (Documentation Update) also complete. See `docs/GAPS.md`
> for per-gap detail. Next up: Phase 5 Reference Distributions (M71+).

## 8. Milestones
### Phase 0 — Foundation
| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M0 | Scope | Define product boundaries. This document. | XS |
| M1 | Application Skeleton | Repo, apps layout, pyproject, CI skeleton | S |
| M2 | Database Registry | PostgreSQL schema, Alembic migrations | M |
| M3 | Artifact Store | Blob store, refs, sha256 ingest/verify | M |
| M4 | Job Runtime | pyjobkit integration, worker lifecycle, base logs | M |
| --- | --- | --- | --- |
| M5 | Worker Capability Model | Worker registry, routing by kind/tags | S |
### Phase 1 — Build Primitives
| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M6 | Toolchain Model | DB model, prebuilt fetch, verify, store | M |
| M7 | Source Fetcher | Fetch by URI/ref/hash, prefetch commands | M |
| --- | --- | --- | --- |
| M8 | Build System / Recipes | Recipe model, cargo/make/cmake/meson executors | L |
| M9 | Package Model / .ofpkg | Format spec, builder, installer, verifier | L |
| M10 | Kernel Model | Kernel DB, config, patches, build, dtb, modules | L |
| M11 | Config / Overlay / Firmware Model | Templates, values, overlays, firmware | M |
### Phase 2 — Assembly
| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M12 | Resolver / Build Plan | Full resolution, resolution_hash, plan output | L |
| M13 | Reproducibility Model | SOURCE_DATE_EPOCH, build env spec, hash chain | M |
| --- | --- | --- | --- |
| M14 | Security Baseline | sha256 on ingest/use, signing model, SBOM, auth | M |
| M15 | Base RootFS Builder | Minimal rootfs from scratch, init system choice | L |
| M16 | RootFS Composer | Install .ofpkg into staging, overlays, services | L |
| M17 | Partition Layout / Image Composer | Layout model, image assembly, boot files | L |
### Phase 3 — Operations
| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M18 | Build Pipeline | End-to-end: plan→fetch→build→compose→image | L |
| M19 | Build History / Logs | Queryable logs, events, build history UI | M |
| M20 | API + Web UI v1 | API spec, SSE events, UI for builds/workers/store | L |
| M21 | Flash Utility | image.flash job, device allowlist, verify | M |
| --- | --- | --- | --- |
| M22 | Test Runner | QEMU boot test, SSH, service healthcheck | M |
| M23 | Store GC / Retention | Retention classes, GC policy, quota alerts | S |
### Phase 4 — Universal OS Builder Expansion

OSFabricum becomes a universal OS Builder / OS Factory. All new work starts at
M24 and **does not restart M0–M23** — it extends the existing primitives with a
universal data model, designers that produce that data, a write API + job
graph, and the competitive feature set. Detailed acceptance criteria for every
milestone below are in **section 18b — Universal OS Builder Milestones (M24+)**.

**4.0 — Foundation of "create" (close structural gaps)**

| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M24 | Implementation Audit & Gap Matrix | Sync docs with code; AUDIT/GAPS/NEXT_ACTIONS | M |
| M25 | Universal OS Builder Model | distribution_class + universal entities | L |
| M26 | Distribution Designer | CRUD/clone/import/export distributions | L |
| M27 | Profile Designer | Full profile fields; resolver consumes profile | L |
| M28 | Universal Build Wizard | 25-step, any-OS, draft→plan→build | XL |
| M29 | Plan API & Build API | Universal write API + pyjobkit job graph | L |

**4.1 — Hardware, boot, image**

| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M30 | Board / Machine / BSP Designer | Boards as BSPs, not just arch | L |
| M31 | Boot Chain Designer | U-Boot/GRUB/EFI/RPi/PXE boot artifacts | L |
| M32 | Initramfs / Early Boot Designer | initramfs profiles + early modules | M |
| M33 | Kernel / Driver Designer | Kconfig index, fragments, driver bundles, ext modules | XL |
| M34 | Filesystem / Image Recipe Designer | Multi-format images, A/B, size policy | L |

**4.2 — Packages, branding, shell, applications**

| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M35 | Package Workspace / Manager | Taxonomy, layers, groups, sets, cache | XL |
| M36 | Package Feature / Variant Manager | Build options → variant hash | L |
| M37 | Package Feed / Repository Publisher | Signed, scoped feeds | L |
| M38 | Runtime Package Policy | Immutable/runtime-install policy + backends | M |
| M39 | Branding / Identity Designer | os-release, splash, login, desktop branding | L |
| M40 | Graphical Shell Designer | no-gui…GNOME/KDE/kiosk GUI stacks | L |
| M41 | Application Catalog Designer | Apps ≠ packages; .desktop/MIME/icons | L |
| M42 | Default Apps / Desktop Integration | mimeapps.list, default handlers, autostart | M |
| M43 | Theme / Icon / Font Designer | Themes/fonts as first-class assets | M |

**4.3 — System concerns**

| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M44 | Users / Groups / Credentials / Secrets | Secrets separated, masked, injected | L |
| M45 | Network Designer | Static/DHCP/bridge/VLAN/Wi-Fi/NAT/VPN | L |
| M46 | Service / Init / Device Manager Designer | Order, deps, healthchecks, udev/mdev | L |
| M47 | Security / Hardening Designer | RO-rootfs, sysctl, LSM, secure boot, gate | L |
| M48 | License / SBOM / Vuln / Source Compliance | SPDX/CycloneDX, gates, source bundles | L |
| M49 | Update / OTA / Recovery Designer | full/A-B/delta/recovery/rollback, signed | L |
| M50 | SDK / Dev Shell / Tooling Export | Cross SDK, sysroot, debug symbols, dev shell | M |
| M51 | Cache / Mirrors / Offline Build Designer | Mirror priority, offline report, pinning | M |
| M52 | QA / Validation Designer | Validation profiles gate promotion | L |
| M53 | Hardware Probe / Import Designer | Probe bundle → board/driver/config draft | L |

**4.4 — Competitive layer (layers, overrides, explain, diff, lockfiles…)**

| # | Milestone | Goal | Effort |
| --- | --- | --- | --- |
| M54 | Layer / Extension Manager | Git-imported layers w/ priority | L |
| M55 | Priority / Override / Masking Engine | override/append/remove/mask/conflict | M |
| M56 | Patch Queue / Source Patch Manager | Ordered patch sets w/ results | M |
| M57 | Dependency Graph Viewer | package/build/runtime/kernel/service graphs | M |
| M58 | Explain / Why Engine | Per-plan-item explain trace | L |
| M59 | Build / Profile / Release Diff | package/kernel/SBOM/size/hash diff | M |
| M60 | System Generations / Rollback Designer | Generations + rollback targets | M |
| M61 | Attended Upgrade / Rebuild Service | Rebuild preserving package set | L |
| M62 | Manifest / Lockfile System | `osfabricum.lock` reproducible plan | M |
| M63 | Importers from Competitors | Buildroot/OpenWrt/Yocto/Debian/Alpine/Nix | L |
| M64 | Build Analysis Dashboard | Time/size/critical-path/cache reports | M |
| M65 | Size / Footprint Optimizer | Budgets, largest files, pruning, diff | M |
| M66 | Boot / Performance Profiler | Boot timeline, slow services, regression | M |
| M67 | Distributed Build Farm / Worker Pools | Labels, affinity, remote cache, quotas | L |
| M68 | Build Isolation / Sandbox Policy | chroot/bwrap/nspawn/podman/VM policy | L |
| M69 | Public Artifact Repository / Publishing | Signed repo index + channels | L |
| M70 | Documentation Update | All designer docs match code direction | M |

### Phase 5 — Reference Distributions

Reference distributions are **validation profiles** for OSFabricum, not
architecture boundaries. They exercise distribution classes end-to-end over the
universal model and **must not introduce special-case build logic**.

| Reference distribution | Class exercised | Profiles (examples) |
|------------------------|-----------------|----------------------|
| **TinyWifi** | router / embedded | default (rpi-zero-2w) |
| **NetOS** | infrastructure / SDN (server) | nervum, testum, ovsdb |
| **Ocultum** | mobile / handheld | communicator, minimal, dev |

> **Distribution-agnostic mandate.** OSFabricum core MUST be
> distribution-agnostic. No build pipeline may contain
> `if distribution == tinywifi/netos/ocultum` special branches. Reference
> distributions are test data and product profiles, not architecture
> boundaries. A reference distribution that cannot be expressed as data over
> the universal model is a model bug, not a reason for a code path.

## 9. MVP Definition

> **Historical (M0–M23 bootstrap).** This section documents the original
> bootstrap MVP that proved the primitives end-to-end. It is retained as the
> historical basis. TinyWifi here is the **router/embedded reference
> distribution** used to exercise the core — not the centre of the product. The
> universal direction (M24+) generalizes this MVP to any distribution class; see
> *Current Implementation Status* and Phase 4/5.

The bootstrap MVP is not "build an image at any cost."
It is a verifiable, traceable, reproducible build of a reference distribution
(TinyWifi) that proves every primitive in the vertical works.

### MVP Acceptance Criteria

1.  board rpi-zero-2w exists in the database
2.  toolchain aarch64-linux-musl is fetched and verified
3.  kernel linux-rpi is built or retrieved from store
4.  package nanodhcp is built and stored as .ofpkg
5.  distribution tinywifi / profile default exists in the database
6.  resolver produces a valid build plan with resolution_hash
7.  prefetch downloads all required sources
8.  worker builds nanodhcp-0.1.0-aarch64.ofpkg
9.  base rootfs is assembled
10. rootfs composer installs .ofpkg packages
11. image composer produces tinywifi-rpi-zero-2w.img.zst
12. every artifact has a sha256 and is queryable
13. build history is visible in CLI and UI

### First Commands That Must Work

# Verify the plan without building
osfabricumctl plan tinywifi/default --board rpi-zero-2w

# Prefetch all sources
osfabricumctl prefetch tinywifi/default --board rpi-zero-2w

# Build one package
osfabricumctl package build nanodhcp --arch aarch64

# Full build
osfabricumctl build tinywifi/default --board rpi-zero-2w

# Check build history
osfabricumctl builds list
osfabricumctl builds logs <build_id>
osfabricumctl artifacts list --distribution tinywifi

## 10. Reference Distribution Worked Example: TinyWifi

> **Reference distribution, not a code path.** Everything below is expressed as
> database records over the universal model. It is the router/embedded
> validation profile (Phase 5). No value here justifies a
> `if distribution == "tinywifi"` branch anywhere in the code.

### Distribution Definition

distribution: tinywifi
description: Minimal Wi-Fi access point OS
default_channel: dev

### Profile: default

profile: default
distribution: tinywifi
board: rpi-zero-2w
arch: aarch64

kernel:
  name: linux-rpi
  version: 6.6.y
  config: tinywifi-rpi-zero-2w

toolchain:
  name: aarch64-linux-musl
  source: bootlin-prebuilt

packages:
  - busybox
  - dropbear
  - hostapd
  - wpa_supplicant
  - nftables
  - nanodhcp
  - webui-agent

services:
  - hostapd
  - nanodhcp
  - webui-agent
  - sshd

init_system: busybox-init

firmware:
  - start4.elf
  - fixup4.dat
  - bcm2710-rpi-zero-2-w.dtb

partition_layout: rpi-2part
  # p1: FAT32 256MB  /boot
  # p2: ext4  rest   /

### Board: rpi-zero-2w

board: rpi-zero-2w
arch: aarch64
soc: bcm2710
boot_scheme: rpi-uboot
firmware_required: true

### Toolchain Decision
For TinyWifi MVP:

Use: Bootlin prebuilt aarch64-linux-musl
Why: Fast to start. No build infra needed. Verified upstream.
Later: crosstool-NG for full control when needed.

### Init System Decision
For TinyWifi MVP:

Use: busybox init
Why: Minimal. Static. No external deps. Matches the target profile.
Not: systemd (too heavy for TinyWifi)
Not: s6/runit (adds complexity before core pipeline is stable)
Later: s6 or runit if service supervision requirements grow.

### Build Recipe: nanodhcp

name: nanodhcp
version: 0.1.0
build_system: cargo

source:
  type: git
  url: https://github.com/4stm4/nanodhcp
  ref: main
  expected_hash: sha256:...

toolchain:
  target: aarch64-unknown-linux-musl

env:
  CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER: aarch64-linux-musl-gcc
  SOURCE_DATE_EPOCH: "0"

steps:
  build:
    - cargo build --release --target aarch64-unknown-linux-musl
  install:
    - install -Dm755 target/aarch64-unknown-linux-musl/release/nanodhcp
        ${DESTDIR}/usr/sbin/nanodhcp
    - install -Dm644 config/nanodhcp.conf
        ${DESTDIR}/etc/nanodhcp.conf

### Expected Output

tinywifi-default-rpi-zero-2w-<build_id>.img.zst
├── sha256: <hash>
├── store_key: images/tinywifi/default/rpi-zero-2w/<version>/tinywifi.img.zst
├── retention_class: staging
└── sbom: sbom/<hash>/cyclonedx.json

### Stack
| Layer | Choice | Reason |
| --- | --- | --- |
| Runtime | Python 3.13+ | Aligns with pyjobkit |
| --- | --- | --- |
| Queue | pyjobkit | Durable SQL queue, retries, routing |
| --- | --- | --- |
| Queue backend | PostgreSQL | SKIP LOCKED support, production-grade |
| API | FastAPI + Pydantic v2 | Strong typing, SSE, pyjobkit-native |
| --- | --- | --- |
| DB access | SQLAlchemy 2 + Alembic | Matches pyjobkit model |
| --- | --- | --- |
| CLI | Typer | Fast operator CLI |
| Dev local | SQLite | Zero-infra local runs |
### Repository Layout

osfabricum/
├── apps/
│   ├── api/          # osfabricum-api
│   ├── worker/       # osfabricum-worker
│   ├── cli/          # osfabricumctl
│   └── web/          # Web UI (after M19)
├── osfabricum/
│   ├── db/           # models, session, migrations bridge
│   ├── jobs/         # job kinds, executors, pyjobkit integration
│   ├── store/        # blob store, refs, ingest, verify
│   ├── resolver/     # build plan resolution
│   ├── builder/      # build system drivers (cargo, make, cmake...)
│   ├── composer/     # rootfs + image assembly
│   ├── flasher/      # image.flash executor
│   ├── fetcher/      # source + toolchain fetch
│   └── schemas/      # Pydantic models, API types
├── migrations/       # Alembic
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
│   ├── ROADMAP.md    # this file
│   ├── ADR/          # architecture decision records
│   └── formats/      # .ofpkg spec, partition layout spec
└── pyproject.toml

## 11. Architecture Decision Records

Key decisions that are fixed for the initial implementation.
Changes require a new ADR in docs/ADR/.

### ADR-001: NetOS is a distribution, not a backend

Status: ACCEPTED

Decision:
  NetOS is represented as a record in the distributions table.
  There is no legacy.netos.build job kind.
  NetOS packages, kernels, and profiles are modelled as data,
  not as code paths in the build system.

Consequences:
  All distributions (tinywifi, netos, ocultum) follow the same
  pipeline. No special cases in the orchestrator.

---

### ADR-002: Toolchain source for MVP

Status: ACCEPTED

Decision:
  Use Bootlin prebuilt toolchains for the TinyWifi MVP.
  Target: aarch64-linux-musl.
  Source: https://toolchains.bootlin.com

Rationale:
  Fastest path to a working cross-compilation environment.
  Verified upstream. No build infrastructure required for toolchain itself.

Future:
  Crosstool-NG when custom toolchain configuration is needed.
  Toolchain model in DB already supports source_type: crosstool-ng.

---

### ADR-003: Init system for TinyWifi

Status: ACCEPTED

Decision:
  Use busybox init for TinyWifi/default profile.

Rationale:
  Minimal footprint. Static binary. No external dependencies.
  Matches the embedded/minimal target profile.

Not chosen:
  systemd  — too heavy for TinyWifi target
  s6/runit — adds complexity before pipeline is stable

Future:
  s6 or runit for distributions that require proper service supervision.
  services table already supports init_system field per service.

---

### ADR-004: Package format

Status: ACCEPTED

Decision:
  Native package format is .ofpkg.
  A .ofpkg is a tar.zst envelope containing:
    manifest.json, files.tar.zst, checksums.sha256,
    scripts/, sbom.json

Rationale:
  Simple. Auditable. No external package manager dependency.
  Installer runs inside OSFabricum, not on the target at runtime.

Consequence:
  OSFabricum is responsible for dependency resolution.
  There is no runtime package manager on the target by default.

---

### ADR-005: Queue ownership

Status: ACCEPTED

Decision:
  pyjobkit owns the queue. OSFabricum does not reimplement queue semantics.
  OSFabricum adds builds, build_jobs, build_events, build_logs
  as its own domain tables that reference pyjobkit job IDs.

---

### ADR-006: Build isolation for MVP

Status: ACCEPTED

Decision:
  Minimum viable isolation for MVP:
    - Fixed sysroot per toolchain
    - SOURCE_DATE_EPOCH=0 for all builds
    - PATH restricted to toolchain + minimal host tools
    - No access to host /usr/lib during cross-compilation

Future:
  Container/namespace isolation for full hermetic builds.
  This is a scope item for M13 (Reproducibility).

---

### ADR-007: Artifact identity

Status: ACCEPTED

Decision:
  SHA-256 is the canonical artifact identity.
  Every artifact must have blob_sha256 verified on ingest and on use.
  Moving refs (branch names) are never accepted as source references
  in release builds.

---

### ADR-008: Web UI is a client

Status: ACCEPTED

Decision:
  The Web UI process does not execute builds, manage workers,
  or own queue state. It is a browser client that talks to the API.

Consequence:
  API can restart without affecting running builds.
  CLI and Web UI are interchangeable clients.

---

## 12. Build Environment Specification

Every build job must declare and record its environment.
This is the foundation of M13 (Reproducibility).

### Environment Spec Schema

```json
{
  "build_env_version": 1,
  "isolation": "sysroot",
  "toolchain_id": "aarch64-linux-musl-13.2.0",
  "toolchain_sha256": "sha256:...",
  "env_vars": {
    "SOURCE_DATE_EPOCH": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "PATH": "/toolchain/bin:/usr/bin:/bin"
  },
  "host_tools": {
    "make": "4.4.1",
    "cargo": "1.78.0",
    "cmake": "3.28.0"
  },
  "sysroot": "/var/lib/osfabricum/cache/toolchains/aarch64-linux-musl-13.2.0"
}

### Reproducibility Hash Chain

source_hash      = sha256(source URI + ref + expected_hash)
recipe_hash      = sha256(build_system + steps + env)
toolchain_hash   = sha256(toolchain artifact blob_sha256)
config_hash      = sha256(kernel config or package config blob)
profile_hash     = sha256(profile inputs_json + board metadata)

resolution_hash  = sha256(
    arch +
    toolchain_hash +
    kernel source_hash + config_hash +
    sorted(package source_hash + recipe_hash) +
    sorted(overlay blob_sha256) +
    partition_layout_hash +
    profile_hash
)

Same resolution_hash means same expected build inputs.
Artifact hash differences with same resolution_hash indicate
non-hermetic build environment or non-deterministic build steps.

### Reproducibility Flags (applied to all builds)

C/C++:
  -ffile-prefix-map=/build/work=.
  -ffile-prefix-map=/var/lib/osfabricum/work=.
  SOURCE_DATE_EPOCH=0

Rust (Cargo):
  CARGO_BUILD_INCREMENTAL=false
  SOURCE_DATE_EPOCH=0
  --remap-path-prefix /build/work=.

Tar archives:
  --sort=name
  --mtime=@0
  --owner=0
  --group=0
  --numeric-owner

## 13. Security Baseline
### Minimum requirements before first release
| Area | Requirement |
| Source integrity | Every source must have expected_hash. Verified on fetch. |
| --- | --- |
| Artifact ingest | sha256 computed and stored. Mismatch = ingest rejected. |
| Artifact use | sha256 re-verified before any compose or publish step. |
| Package install | .ofpkg checksums.sha256 verified before install into rootfs. |
| Artifact signing | Release artifacts signed. Bundle stored next to artifact. |
| SBOM | CycloneDX generated for every promoted image. |
| Log safety | Secrets never emitted to build_logs. Masking at worker level. |
| API auth | Token-based auth from day one. Owner/operator/viewer roles. |
| --- | --- |
| Worker auth | Workers authenticate with per-worker tokens. |
| Flash safety | Explicit device allowlist. Read-back verify. No sparse writes. |
### Signing Model
Phase 1 (MVP):

sha256 on every artifact        → always
Cosign sign-blob                → on release artifacts
bundle stored in store          → attestations/<subject-sha256>/cosign.bundle

Phase 2 (post-MVP):

GitHub artifact attestations    → for public repos
in-toto / SLSA provenance       → sidecar per build
SBOM signed separately          → sbom.<hash>.cyclonedx.json + bundle

### SBOM Generation
Every promoted image produces:

sbom/<image-sha256>/cyclonedx.json
  → components: all installed packages + versions
  → dependencies: resolved graph
  → tools: build toolchain version
  → metadata: distribution, profile, board, build_id, resolution_hash

Source: derived from package manifest.json files installed into rootfs.
Tool: cdxgen or manual generation from .ofpkg manifests.

### API Roles
| Role | Permissions |
| --- | --- |
| viewer | Read builds, artifacts, catalog. Download artifacts. |
| operator | Create builds, cancel builds, manage prefetch, manage cache. |
| owner | All operator permissions + manage releases, manage workers, |
delete artifacts, manage retention, manage users.
| admin | Full access including internal queue dashboard. |
## 14. Observability Plan
### Structured Logs
Every log line must include:

{
  "ts": "2025-01-01T00:00:00Z",
  "level": "info",
  "build_id": "bld_01...",
  "job_id": "job_01...",
  "worker_id": "worker-aarch64-01",
  "step_kind": "package.build",
  "package": "nanodhcp",
  "version": "0.1.0",
  "arch": "aarch64",
  "message": "build completed"
}

### Metrics
| Metric | Type | Labels |
| --- | --- | --- |
| osf_build_duration_seconds | histogram | distribution, profile, board |
| osf_build_total | counter | status (success/failed/cancel) |
| --- | --- | --- |
| osf_queue_depth | gauge | kind |
| osf_worker_active_jobs | gauge | worker_id, kind |
| --- | --- | --- |
| osf_cache_hit_ratio | gauge | cache_type |
| osf_store_bytes_total | gauge | retention_class |
| --- | --- | --- |
| osf_gc_deleted_bytes_total | counter | retention_class |
| --- | --- | --- |
| osf_artifact_ingest_total | counter | kind, status |
| --- | --- | --- |
| osf_source_fetch_duration_seconds | histogram | source_type |
| --- | --- | --- |
| osf_package_build_duration_seconds | histogram | build_system, arch |
| osf_qemu_boot_duration_seconds | histogram | board |
| osf_flash_verify_failures_total | counter | board |
### Traces
One trace per build run.
Spans per executor step:

build/<build_id>
  resolve.plan
  source.fetch/<package>      (parallel)
  toolchain.fetch
  kernel.build
  package.build/<name>        (parallel)
  rootfs.compose
  image.compose
  image.test
  artifact.sign
  artifact.attest
  release.publish

### Health Endpoints
| Endpoint | Checks |
| --- | --- |
| /healthz | Process alive |
| /readyz | DB reachable + queue ping + store writable |
| --- | --- |
| /metrics | Prometheus format |
## 15. CI/CD Pipeline
### Pipeline Stages
| Stage | Trigger | What runs |
| --- | --- | --- |
| lint / format / type | every PR | ruff, mypy, schema validation |
| unit tests | every PR | resolver, store, installer, CLI, API |
| integration tests | every PR / main | PostgreSQL + pyjobkit + store + worker |
| --- | --- | --- |
| package build test | package-related PRs | .ofpkg build + install + verify |
| QEMU smoke | nightly / release branch | boot image, SSH reachable, service health |
| security metadata | nightly | SBOM generation, dependency graph, vuln scan |
| release build | tags / manual promote | build + sign + attest + publish manifest |
| scheduled hygiene | daily | store.gc, cache verify, vuln DB sync |
### Test Layers
| Layer | Subject | Required for |
| --- | --- | --- |
| unit | resolver, store, .ofpkg parser, CLI, API | all PRs |
| integration | pyjobkit + DB + store + worker lifecycle | all PRs |
| --- | --- | --- |
| package build | .ofpkg build / install / verify | package PRs |
| QEMU runtime | boot, SSH, service healthcheck | pre-release |
| flash / hardware | write, read-back, boot smoke | release candidate |
## 16. Glossary
| Term | Definition |
| --- | --- |
| distribution | A named OS product. A record in the distributions table. |
| --- | --- |
| profile | A named configuration of a distribution for a specific purpose. |
| board | A supported hardware or virtual target platform. |
| toolchain | A cross-compilation toolchain with target arch, libc, version. |
| .ofpkg | Native OSFabricum binary package format. |
| build plan | Resolver output for a distribution/profile/board triple. |
| resolution_hash | Deterministic hash of all build plan inputs. |
| --- | --- |
| artifact | Any immutable output stored with sha256 and metadata. |
| --- | --- |
| store_key | Human-readable path alias for an artifact in the store. |
| retention_class | Policy classification controlling GC behaviour for an artifact. |
| --- | --- |
| worker | Independent process that claims and executes jobs by kind/tags. |
| --- | --- |
| job kind | Logical step type (e.g. package.build, rootfs.compose). |
| --- | --- |
| prefetch | Downloading sources and toolchains before a build starts. |
| --- | --- |
| base rootfs | Minimal filesystem skeleton before packages are installed. |
| overlay | A directory tree merged into the rootfs after package install. |
| partition layout | Description of disk partition structure for a target image. |
| firmware blob | Board-specific binary required for boot (e.g. RPi start4.elf). |
| first boot task | A script or service that runs only on the first system boot. |
| SBOM | Software Bill of Materials. CycloneDX or SPDX format. |
| provenance | Record of how, when, and from what inputs an artifact was built. |
| channel | Release track. Examples: dev, stable, lts, nightly. |
| --- | --- |
| resolution_hash | Unique fingerprint of a resolved build plan. Enables repeatability. |
## 17. Open Questions
Items not yet decided. Must be resolved before the relevant milestone.

| # | Question | Blocks |
| --- | --- | --- |
| 1 | Shared library strategy: static vs dynamic linking? | M9, M16 |
| 2 | Dependency solver algorithm: naive graph or SAT? | M12 |
| 3 | Container/namespace isolation for hermetic builds? | M13 |
| 4 | s6/runit support for netos profiles? | M25 |
| 5 | Remote artifact store: S3-compatible or local only? | M18+ |
| 6 | Multi-arch parallel builds: same worker or separate? | M18 |
| 7 | Cosign vs GitHub attestations as primary signing? | M14 |
| 8 | Package signing: per-package or per-release-bundle? | M14 |
| 9 | Web UI framework choice? | M20 |
| 10 | First-boot config format: custom or cloud-init? | M11 |
## 18. Milestones — Detailed Acceptance Criteria
### M1 — Application Skeleton

✓ osfabricum/ repo exists with layout defined in section 10
✓ osfabricum-api starts and responds on /healthz
✓ osfabricum-worker starts and logs "waiting for jobs"
✓ osfabricumctl --help shows all top-level commands
✓ pyproject.toml defines all three entry points
✓ CI runs lint + type check on every PR
✓ SQLite works for local development without config

### M2 — Database Registry

✓ All tables from section 4 exist in migrations
✓ alembic upgrade head runs cleanly on PostgreSQL and SQLite
✓ architectures seed data: aarch64, x86_64, riscv64
✓ boards seed data: rpi-zero-2w, qemu-x86_64
✓ distributions seed data: tinywifi, netos, ocultum
✓ osfabricumctl catalog list distributions works
✓ osfabricumctl catalog list boards works

### M3 — Artifact Store

✓ Blob ingest computes sha256 and rejects mismatch
✓ Same blob stored twice = one blob, two refs
✓ store verify checks all blobs against stored sha256
✓ Artifact metadata row created on every ingest
✓ osfabricumctl store verify runs without errors on empty store
✓ osfabricumctl artifacts list works

### M6 — Toolchain Model

✓ toolchains and toolchain_artifacts tables exist
✓ osfabricumctl toolchain add aarch64-linux-musl --source bootlin
✓ osfabricumctl toolchain fetch aarch64-linux-musl downloads and stores
✓ sha256 verified after fetch
✓ toolchain artifact visible in store
✓ osfabricumctl toolchain verify aarch64-linux-musl passes

### M9 — Package Model / .ofpkg

✓ .ofpkg format spec documented in docs/formats/ofpkg.md
✓ osfabricumctl package build nanodhcp --arch aarch64 produces .ofpkg
✓ Tampered .ofpkg (modified files.tar.zst) rejected by installer
✓ checksums.sha256 verified before install
✓ manifest.json schema validated on build and on install
✓ sbom.json present and valid CycloneDX

### M12 — Resolver / Build Plan

✓ osfabricumctl plan tinywifi/default --board rpi-zero-2w
  → prints valid build plan JSON
  → includes resolution_hash
  → lists missing_artifacts
  → lists required_jobs
✓ Same inputs produce same resolution_hash across runs
✓ Invalid board/profile combination fails before any job is enqueued
✓ Missing toolchain reported in plan output, not as a runtime error

### Phase 5 Reference — TinyWifi Native Build (validation profile)

> Formerly numbered "M24". Renumbered: M24 is now *Implementation Audit & Gap
> Matrix*. TinyWifi is the router/embedded reference distribution; these are its
> Phase 5 validation criteria, met purely through data over the universal model.

✓ osfabricumctl build tinywifi/default --board rpi-zero-2w completes
✓ tinywifi-rpi-zero-2w.img.zst exists in artifact store
✓ Image boots under QEMU (aarch64)
✓ SSH accessible on boot
✓ hostapd process running
✓ nanodhcp service running
✓ webui-agent service running
✓ All artifacts have sha256 in database
✓ Build history visible: osfabricumctl builds list
✓ Logs queryable: osfabricumctl builds logs <build_id>
✓ SBOM generated and stored for the image
✓ resolution_hash recorded on the build

## 19. Milestones — Acceptance Criteria (continued)

### M4 — Job Runtime / pyjobkit

✓ pyjobkit SQL backend initialised on PostgreSQL
✓ pyjobkit migrations run cleanly alongside OSFabricum migrations
✓ Worker process starts, registers heartbeat, claims a test job
✓ Job completes, status reflected in build_jobs table
✓ Job fails, retry policy applied correctly
✓ Worker crashes mid-job, lease expires, job re-queued
✓ build_events rows written for: queued, claimed, started, completed, failed
✓ build_logs rows written line-by-line during job execution
✓ pyjobkit dashboard accessible at /internal/queue (admin only)
✓ /metrics exposes queue depth per job kind

### M5 — Worker Capability Model

✓ workers table populated on worker startup via self-registration
✓ Worker declares kinds[] and tags[] on registration
✓ Worker updates last_seen_at on heartbeat
✓ Job routed only to workers matching required kind and tags
✓ Worker with cap:qemu=false never receives image.test jobs
✓ Worker with arch:x86_64 never receives kernel.build jobs tagged arch:aarch64
✓ osfabricumctl workers list shows all workers with capabilities and status
✓ Stale worker (no heartbeat > 3× lease_ttl) marked as offline

### M7 — Source Fetcher / Prefetch

✓ source.fetch job downloads source by URI + ref + expected_hash
✓ Downloaded source sha256 verified against expected_hash
✓ Mismatch → job fails, source not stored
✓ Duplicate fetch of same source → cache hit, no re-download
✓ osfabricumctl prefetch tinywifi/default --board rpi-zero-2w
→ enqueues source.fetch for all packages in build plan
→ enqueues toolchain.fetch
→ reports progress per source
✓ osfabricumctl prefetch --compliance mode fetches legal-only sources too
✓ VCS sources (git) pinned to commit hash, never branch name in release mode
✓ Offline mode: build proceeds if all sources already in cache
✓ Offline mode: fails fast and clearly if any source missing

### M8 — Build System / Recipes

✓ build_recipes table stores steps_json and env_json per package version
✓ RecipeExecutor supports: cargo, make, cmake, meson, autotools, custom
✓ Each build system driver implements: prepare, configure, build, install
✓ DESTDIR staging respected by all drivers
✓ SOURCE_DATE_EPOCH=0 injected into all build environments
✓ PATH restricted to toolchain + declared host tools only
✓ Build fails if undeclared host tool is invoked
✓ Recipe hash computed from: build_system + steps + env + toolchain
✓ Same recipe_hash + same source_hash → cache hit, skip rebuild
✓ Build output captured line-by-line into build_logs
✓ Failed build preserves work directory for inspection (retention: failed-run)

### M10 — Kernel Model

✓ kernels and kernel_configs tables populated for linux-rpi 6.6.y
✓ kernel.build job cross-compiles kernel for aarch64
✓ Outputs stored as artifacts:
- Image        (kind: kernel)
- modules.tar.zst (kind: kernel-modules)
- bcm2710-rpi-zero-2-w.dtb (kind: dtb)
✓ Kernel config blob stored and linked via kernel_configs
✓ Config hash included in resolution_hash
✓ osfabricumctl kernel build linux-rpi --board rpi-zero-2w
✓ Kernel artifact queryable: osfabricumctl artifacts list --kind kernel
✓ Cached kernel reused if source_hash + config_hash unchanged
✓ Patches applied deterministically and recorded in kernel metadata

### M11 — Config / Overlay / Firmware Model

✓ config_templates table holds named templates with schema_json
✓ config_values table holds per-profile/per-board values
✓ Template rendering produces concrete config files (hostapd.conf, etc.)
✓ Rendered configs stored as artifacts and linked to build
✓ overlays table references artifact containing overlay directory tree
✓ Overlay applied after package install via deterministic merge
✓ firmware_blobs table populated for rpi-zero-2w:
start4.elf, fixup4.dat, bcm2710-rpi-zero-2-w.dtb
✓ Firmware artifacts fetched, sha256 verified, stored
✓ Firmware placement field used by image composer for correct partition
✓ first_boot_tasks stored and installed as service or script in rootfs
✓ All config rendering is deterministic (same inputs → same output bytes)

### M13 — Reproducibility Model

✓ resolution_hash computed per build plan as defined in section 12
✓ resolution_hash stored on builds table row
✓ Two builds with same resolution_hash produce same resolution_hash
✓ SOURCE_DATE_EPOCH=0 applied to all builds
✓ Reproducibility flags applied to C/C++ and Rust builds (section 12)
✓ Tar archives produced with --sort=name --mtime=@0 --numeric-owner
✓ build_environment spec recorded as artifact for every build
✓ osfabricumctl builds diff <id1> <id2>
→ shows inputs that differ between two builds
✓ Artifact hash difference with same resolution_hash logged as warning
✓ osfabricumctl builds reproduce <id>
→ re-runs build with same resolution_hash
→ reports whether output artifact sha256 matches

### M14 — Security Baseline

✓ Every source fetch verifies expected_hash before storing
✓ Every artifact ingest verifies sha256 before committing
✓ Checksum mismatch → ingest rejected, error logged, job failed
✓ sha256 re-verified before rootfs.compose and image.compose steps
✓ .ofpkg checksums.sha256 verified before install into rootfs
✓ API requires token authentication on all non-health endpoints
✓ Owner/operator/viewer roles enforced per endpoint
✓ Workers authenticate with per-worker tokens
✓ No secrets emitted in build_logs (masking applied at worker level)
✓ Release artifacts signed with Cosign sign-blob
✓ Cosign bundle stored at attestations/<sha256>/cosign.bundle
✓ CycloneDX SBOM generated for every promoted image
✓ SBOM stored at sbom/<image-sha256>/cyclonedx.json
✓ SBOM signed separately, bundle stored next to SBOM
✓ Signing keys never stored in cache or logs
✓ Flash job requires explicit device allowlist entry

### M15 — Base RootFS Builder

✓ Base rootfs built from scratch for aarch64-linux-musl
✓ Contains: busybox, musl libc, /etc skeleton, /dev minimal nodes
✓ /etc/passwd, /etc/group, /etc/shadow created with correct defaults
✓ Init system: busybox init, /etc/inittab present
✓ No host-system paths or timestamps leak into base rootfs
✓ Base rootfs stored as artifact: kind=base-rootfs
✓ sha256 recorded, base rootfs reused if inputs unchanged
✓ osfabricumctl rootfs build-base --arch aarch64 --libc musl
✓ Base rootfs boots under QEMU to a shell prompt
✓ Build is reproducible: same inputs → same sha256

### M16 — RootFS Composer

✓ rootfs.compose job takes: base rootfs + package list + overlays + configs
✓ Packages installed in dependency order
✓ Each .ofpkg verified (sha256 + manifest) before install
✓ preinst script executed before file extraction
✓ files.tar.zst extracted into staging DESTDIR
✓ postinst script executed after file extraction
✓ Overlays merged deterministically after package install
✓ Config files rendered and placed correctly
✓ Services registered according to init_system setting
✓ first_boot_tasks installed as /etc/osfabricum/first-boot.d/ scripts
✓ Final rootfs stored as artifact: kind=rootfs, compression=zstd
✓ Rootfs artifact sha256 recorded
✓ osfabricumctl compose rootfs tinywifi/default --board rpi-zero-2w

### M17 — Partition Layout / Image Composer

✓ partition_layouts table populated for rpi-2part:
p1: FAT32 256MB /boot
p2: ext4  rest  /
✓ layout_json schema documented in docs/formats/partition-layout.md
✓ image.compose job:
→ creates raw image of correct size
→ formats partitions per layout
→ copies kernel, dtb, firmware to /boot partition
→ copies rootfs to / partition
→ writes cmdline.txt and config.txt
✓ Output: tinywifi-rpi-zero-2w.img.zst (kind=image)
✓ Image sha256 recorded
✓ Full dd write only. No sparse writes.
✓ osfabricumctl compose image tinywifi/default --board rpi-zero-2w
✓ Image mountable via loopback for inspection

### M18 — Build Pipeline

✓ osfabricumctl build tinywifi/default --board rpi-zero-2w
→ runs full pipeline: resolve → fetch → build → compose → image
✓ resolve.plan job runs first, produces build plan
✓ source.fetch and toolchain.fetch run in parallel
✓ package.build jobs run in parallel where dependencies allow
✓ kernel.build runs in parallel with package builds
✓ rootfs.compose waits for all package.build jobs to complete
✓ image.compose waits for rootfs.compose and kernel.build
✓ Each step records start/end times in build_events
✓ Build status transitions: queued→running→completed / failed / cancelled
✓ Cancelled build stops all pending jobs cleanly
✓ Failed step records failure reason in build_events
✓ Completed build: all artifacts registered, build_id queryable

### M19 — Build History / Logs / Events

✓ osfabricumctl builds list
→ shows: build_id, distribution, profile, board, status, duration
✓ osfabricumctl builds show <build_id>
→ shows: full build plan, all jobs, all artifacts, timings
✓ osfabricumctl builds logs <build_id>
→ streams or paginates build_logs rows
→ supports --job-id, --stream (stdout/stderr), --follow
✓ GET /v1/builds/{id}/events SSE stream works
→ emits: queued, claimed, started, progress, completed, failed
✓ Build history queryable by: distribution, profile, board, status, date
✓ Logs retained per retention policy (failed-run: 30 days)
✓ Logs queryable independently of worker process lifecycle

### M20 — API + Web UI v1

✓ All endpoints from section 6 API Surface implemented
✓ SSE event stream works for live build monitoring
✓ Token auth enforced on all non-health endpoints
✓ /healthz and /readyz return correct status
✓ /metrics returns valid Prometheus format
✓ Web UI: create build job
✓ Web UI: view build queue and status
✓ Web UI: view worker inventory and health
✓ Web UI: stream build logs live
✓ Web UI: download image artifact
✓ Web UI: trigger prefetch
✓ Web UI: browse artifact catalog
✓ Web UI builds nothing itself
✓ Web UI works without WebSocket — SSE only

### M21 — Flash Utility

✓ image.flash job exists with no auto-retry
✓ Flash worker requires cap:flash capability
✓ Device must be on explicit allowlist before flash proceeds
✓ osfabricumctl flash list-devices → lists allowed devices
✓ osfabricumctl flash image <artifact_id> --device /dev/sdX
→ downloads artifact from store
→ verifies sha256 before write
→ performs full dd write (no sparse)
→ verifies written media sha256 after write
✓ Flash refuses to write to non-allowlisted device
✓ Flash failure recorded in build_events
✓ osfabricumctl flash verify <artifact_id> --device /dev/sdX
→ standalone verify without re-flash

### M22 — Test Runner

✓ image.test job runs QEMU boot test for aarch64
✓ Test declares: image artifact_id, board, timeout, test suite
✓ QEMU boots image, waits for login prompt or SSH
✓ SSH reachable check passes
✓ Service healthchecks for TinyWifi:
✓ hostapd process is running
✓ nanodhcp service is running
✓ webui-agent service is running
✓ sshd is running
✓ Package manifest check: all declared packages present in rootfs
✓ Test results stored in build_events
✓ Failing test blocks promotion to stable channel
✓ QEMU test output stored as log artifact
✓ osfabricumctl test run <build_id> --suite tinywifi-smoke

### M23 — Store GC / Retention Policies

✓ Retention classes enforced per section 5
✓ release and promoted artifacts never deleted by GC
✓ staging artifacts deleted after 90 days if unpinned
✓ cache-hot artifacts managed by LRU within quota
✓ cache-cold artifacts deleted after 7-14 days
✓ failed-run logs retained longer than failed-run blobs
✓ osfabricumctl store gc --dry-run shows what would be deleted
✓ osfabricumctl store gc --class cache-cold --older-than 14d
✓ osfabricumctl store stats shows usage per retention class
✓ Quota alerts emitted as metrics: osf_store_bytes_total per class
✓ GC never deletes pinned artifacts
✓ GC never deletes artifacts referenced by a release record

### Phase 5 Reference — NetOS Native Distribution (validation profile)

> Formerly numbered "M25". Renumbered: M25 is now *Universal OS Builder Model*.
> NetOS is the infrastructure/SDN (server-class) reference distribution.

✓ distribution: netos exists in DB
✓ Profiles defined: nervum, testum, ovsdb
✓ Each profile has packages, services, overlays, configs in DB
✓ osfabricumctl plan netos/nervum --board qemu-x86_64 succeeds
✓ osfabricumctl build netos/nervum --board qemu-x86_64 completes
✓ No legacy backend invoked at any step
✓ Image boots under QEMU
✓ All netos-specific services pass healthchecks
✓ SBOM generated for netos image
✓ NetOS packages built and stored as .ofpkg artifacts

### Phase 5 Reference — Ocultum Distribution (validation profile)

> Formerly numbered "M26". Renumbered: M26 is now *Distribution Designer*.
> Ocultum is the mobile/handheld reference distribution.

✓ distribution: ocultum exists in DB
✓ Profiles defined: communicator, minimal, dev
✓ osfabricumctl plan ocultum/minimal --board qemu-x86_64 succeeds
✓ osfabricumctl build ocultum/minimal --board qemu-x86_64 completes
✓ Image boots and passes smoke tests
✓ SBOM generated

---

## 18b. Universal OS Builder Milestones (M24+)

Each milestone is specified as a full vertical: **DB model · API · CLI · UI ·
worker jobs · artifacts · tests · acceptance criteria**. No milestone is "done"
until that vertical exists. None of these milestones restart M0–M23; they extend
the existing primitives. Companion design docs:
[`OS_BUILDER_WIZARD`](OS_BUILDER_WIZARD.md),
[`PACKAGE_WORKSPACE`](PACKAGE_WORKSPACE.md),
[`KERNEL_DRIVER_DESIGNER`](KERNEL_DRIVER_DESIGNER.md),
[`BRANDING_DESIGNER`](BRANDING_DESIGNER.md),
[`GRAPHICAL_SHELL_DESIGNER`](GRAPHICAL_SHELL_DESIGNER.md),
[`LAYER_MODEL`](LAYER_MODEL.md), [`EXPLAIN_ENGINE`](EXPLAIN_ENGINE.md),
[`LOCKFILE`](LOCKFILE.md), [`BUILD_ANALYSIS`](BUILD_ANALYSIS.md).

---

### M24 — Implementation Audit & Gap Matrix

**Goal:** Synchronize documentation with the actual state of the code.
**Deliverables:** `docs/IMPLEMENTATION_AUDIT.md`, `docs/GAPS.md`,
`docs/NEXT_ACTIONS.md`, plus this *Current Implementation Status* section.
**DB/API/CLI/UI/Jobs/Artifacts:** n/a (documentation milestone).
**Tests:** doc-lint only (links resolve; status vocabulary used consistently).
**Acceptance:**
- M0–M23 verified across the full vertical; every milestone has a status.
- Every `partial`/`missing` item has a *next action*.
- No "done" claim without code **and** tests.
- Read-only API gaps, UI gaps, pipeline gaps, and hardcoded-distribution risks
  are explicitly called out.

### M25 — Universal OS Builder Model

**Goal:** A universal data model that can express any OS class as records.
**DB (new/extended):** `distribution`, `distribution_class`, `profile`,
`board`, `architecture`, `toolchain`, `kernel`, `kernel_config`, `package_set`,
`package_group`, `boot_scheme`, `image_recipe`, `branding_profile`,
`graphical_profile`, `network_profile`, `security_profile`, `update_strategy`,
`validation_profile`. Migration uses **explicit DDL** (retires the
`metadata.create_all` baseline for new tables; closes G-23).
**`distribution_class` values:** embedded, router, server, desktop, kiosk,
appliance, mobile-handheld, recovery, firmware, container-host,
hypervisor-host.
**API:** `GET /v1/distribution-classes`; class field on distribution/profile
read+write endpoints (M26/M27).
**CLI:** `osfabricumctl catalog list distribution-classes`.
**UI:** class selectors surfaced in M26/M27 designers.
**Jobs/Artifacts:** none new (modelling milestone).
**Tests:** model unit tests; a distribution + profile of **each** class can be
created and resolved (no reference distribution required).
**Acceptance:**
- A distribution can be created with no tie to any reference distribution.
- A profile can be created for any distribution and can select class, board,
  kernel, packages, branding, graphical profile, services, image layout.
- The build plan is assembled from data, not a hardcoded scenario.

### M26 — Distribution Designer

**Goal:** Create and manage OS products through API + UI.
**DB:** `distribution` (extended: class, default_channel, metadata),
`distribution_export` snapshots.
**API:** `GET /v1/distributions`, `POST /v1/distributions`,
`GET /v1/distributions/{id}`, `PATCH /v1/distributions/{id}`,
`DELETE /v1/distributions/{id}`, `POST /v1/distributions/{id}/clone`,
`POST /v1/distributions/import`, `GET /v1/distributions/{id}/export`.
**CLI:** `osfabricumctl distribution create|show|edit|clone|delete`,
`osfabricumctl distribution import --file x.yaml`,
`osfabricumctl distribution export <id> > x.yaml`.
**UI:** `/distributions`, `/distributions/new`, `/distributions/{id}`,
`/distributions/{id}/{profiles,layers,branding,releases}`.
**Jobs:** `distribution.import`, `distribution.export` (validation + render).
**Artifacts:** distribution YAML export bundle (`kind=distribution-export`).
**Tests:** create/clone/import/export round-trip; import is validated, not
trusted blindly.
**Acceptance:** create a new OS from the UI; import/export distribution YAML;
clone; assign class + default channel; **no special code path for reference
distributions** (clone of TinyWifi is data only).

### M27 — Profile Designer

**Goal:** Full, versioned, diffable profiles that the resolver actually
consumes (closes G-02).
**DB:** `profile` (fields below), `profile_version`, `profile_package_set`,
`profile_service_set`. **Profile fields:** distribution, name, inherits,
board constraints, architecture constraints, libc policy, init system, device
manager, default kernel policy, default toolchain policy, package sets, service
sets, config values, scripts, overlays, branding profile, graphical profile,
network profile, security profile, image recipe, update strategy, validation
profile.
**API:** `GET/POST /v1/profiles`, `GET/PATCH /v1/profiles/{id}`,
`POST /v1/profiles/{id}/clone`, `GET /v1/profiles/{id}/versions`,
`POST /v1/profiles/{id}/diff`, `GET /v1/profiles/{id}/export`,
`POST /v1/profiles/import`.
**CLI:** `osfabricumctl profile create|edit|clone|version|diff|export|import`.
**UI:** `/profiles`, `/profiles/new`, `/profiles/{id}`, `/profiles/{id}/edit`,
`/profiles/{id}/diff`, `/profiles/{id}/versions`.
**Jobs:** `profile.resolve-preview` (dry resolve without build).
**Artifacts:** profile snapshot/export.
**Tests:** create without building; clone; version; diff; export/import;
inheritance merge; **resolver uses profile inputs** (two profiles → two package
sets).
**Acceptance:** all of the above; the resolver wires `_merged_inputs` into
selection.

### M28 — Universal Build Wizard

**Goal:** One wizard builds any OS class. See
[`OS_BUILDER_WIZARD.md`](OS_BUILDER_WIZARD.md).
**UI entry:** `/build/new` (25 steps: distribution → profile → class → board →
arch/libc → toolchain → boot chain → kernel source → kernel options/drivers →
base rootfs → package layers/groups/packages → package features → services/init/
device manager → network → users/groups/secrets → graphical shell → applications/
default apps → branding/themes/fonts → filesystem/image layout → updates/recovery
→ security/hardening → compliance/SBOM/license → validation/tests → review plan →
prefetch/build/test/sign/publish).
**API:** wizard persists drafts via `POST /v1/build-drafts`,
`PATCH /v1/build-drafts/{id}`; submits via M29 (`POST /v1/plan`,
`POST /v1/builds`). **No build logic in the UI** — it only calls the API.
**CLI:** `osfabricumctl build new --from <distribution|profile|build|image>`.
**Jobs:** delegates to M29 job graph.
**Artifacts:** build draft; build plan artifact.
**Tests:** integration/e2e — wizard → plan → build for a **non-reference**
distribution (first real e2e; closes G-18).
**Acceptance:** wizard is not tied to one OS; can start from distribution,
profile, previous build, or imported image; can save a draft; can build a plan
without building; can create a build; shows missing artifacts, cache
hits/misses, and **explain** for packages/kernel options/jobs.

### M29 — Plan API & Build API

**Goal:** Universal write API + real pyjobkit job graph (closes G-01, G-03).
**API:** `POST /v1/plan`, `POST /v1/plan/validate`, `POST /v1/plan/diff`,
`POST /v1/prefetch`, `POST /v1/builds`, `GET /v1/builds`, `GET /v1/builds/{id}`,
`GET /v1/builds/{id}/events`, `GET /v1/builds/{id}/logs`,
`GET /v1/builds/{id}/artifacts`, `POST /v1/builds/{id}/cancel`,
`POST /v1/builds/{id}/rebuild`, `POST /v1/builds/{id}/clone-as-profile`.
`POST /v1/plan` accepts `distribution_id`, `profile_id`, `board_id`, and
`overrides`: kernel, kernel_options, driver_bundles, package_groups,
package_set, package_features, boot_chain, image_recipe, branding,
graphical_profile, network_profile, security_profile, update_strategy,
validation_profile. **Auth enforced on all write endpoints** (closes G-24).
**CLI:** `osfabricumctl plan` (now POST-capable with `--override`),
`osfabricumctl prefetch`, `osfabricumctl build`, `... rebuild`,
`... clone-as-profile`.
**DB:** `build_draft`, `build_plan_artifact` ref on `builds`.
**Jobs (pyjobkit graph):** `resolve.plan` → (`source.fetch`/`toolchain.fetch`
∥ `kernel.build`/`package.build×N`) → `rootfs.compose` → `image.compose` →
`image.test`/`artifact.sign`/`artifact.attest` → `release.publish`.
**Artifacts:** build plan JSON (`kind=build-plan`), per-step logs/events.
**Tests:** plan-with-overrides; build-from-plan; cancel; rebuild;
clone-as-profile; `package.build` runs as a job.
**Acceptance:** Plan API does **not** start a build; Build API starts a job
graph; Build accepts a saved profile, a saved plan, or a wizard request;
creates a build record + plan artifact + pyjobkit jobs; status flows via
events/logs; cancel works.

### M30 — Board / Machine / BSP Designer

**Goal:** Hardware targets as boards/machines/BSPs, not bare arch.
**DB:** `boards` (extended), `board_revisions`, `soc_families`, `boot_schemes`,
`board_firmware`, `board_device_trees`, `board_default_kernels`,
`board_default_toolchains`, `board_supported_layouts`, `board_flash_methods`,
`board_test_methods`, `board_probe_profiles`.
**API:** `GET/POST /v1/boards`, `GET/PATCH/DELETE /v1/boards/{id}`,
`.../firmware`, `.../device-trees`, `.../boot`, `.../layouts`, `.../flash`,
`.../test`, `POST /v1/boards/{id}/clone`.
**CLI:** `osfabricumctl board create|show|edit|clone`, `board firmware add`,
`board dtb add`, `board boot set`, `board test add`.
**UI:** `/boards`, `/boards/new`, `/boards/{id}`, `/boards/{id}/{firmware,
device-tree,boot,test}`.
**Jobs:** `board.firmware.fetch`, `board.dtb.fetch`, `board.validate`.
**Artifacts:** firmware blobs, DTB/DTBO, board manifest.
**Tests:** create custom board + revision; attach boot scheme/firmware/DTB/
layouts/flash/test methods.
**Acceptance:** all of the above resolvable into a build plan per board
revision.

### M31 — Boot Chain Designer

**Goal:** Boot chain is a first-class, selectable, templated part of the plan.
**Support:** direct kernel boot, Raspberry Pi firmware boot, U-Boot, GRUB,
systemd-boot, EFI, PXE/netboot, custom vendor boot.
**DB:** `boot_chains`, `boot_chain_templates`, `boot_chain_files`,
`boot_chain_bindings` (board/profile).
**API:** `GET/POST /v1/boot-chains`, `POST /v1/boot-chains/{id}/render`,
`POST /v1/boot-chains/{id}/validate`.
**CLI:** `osfabricumctl boot-chain create|render|validate|bind`.
**UI:** boot chain selector in M28 step 7; `/boot-chains`.
**Jobs:** `boot.render`, `boot.validate`.
**Artifacts:** boot manifest, boot partition files, `grub.cfg`,
`extlinux.conf`, `u-boot.env`, `cmdline.txt`, `config.txt`, initramfs
reference, DTB/DTBO placement.
**Tests:** boot files generated from templates per board/profile; validation
catches missing kernel/initramfs/DTB.
**Acceptance:** boot chain is part of the build plan; files are artifacts;
selectable per board/profile; validatable.

### M32 — Initramfs / Early Boot Designer

**Goal:** Model early boot.
**Support:** no initramfs, minimal, recovery, encrypted-root unlock, network
boot, debug shell, factory reset.
**DB:** `initramfs_profiles`, `initramfs_packages`, `initramfs_scripts`,
`initramfs_hooks`, `initramfs_artifacts`.
**API:** `GET/POST /v1/initramfs-profiles`,
`POST /v1/initramfs-profiles/{id}/build`.
**CLI:** `osfabricumctl initramfs create|build|attach`.
**UI:** initramfs selector in M28 step 9–10; `/initramfs`.
**Jobs:** `initramfs.resolve`, `initramfs.build`.
**Artifacts:** initramfs image (`kind=initramfs`), included-modules manifest.
**Tests:** packages/scripts resolved; early-boot kernel modules included;
artifact generated; boot chain references it.
**Acceptance:** selectable in profile; resolved; built; referenced by boot
chain.

### M33 — Kernel / Driver Designer

**Goal:** A real kernel and driver designer where options come from the
selected kernel **source tree + Kconfig** for the selected arch/version — never
a flat checkbox list. See [`KERNEL_DRIVER_DESIGNER.md`](KERNEL_DRIVER_DESIGNER.md).
**DB:** `kernel_kconfig_indexes`, `kernel_option_symbols`,
`kernel_option_dependencies`, `kernel_option_choices`, `kernel_config_presets`,
`kernel_config_fragments`, `kernel_config_values`, `kernel_config_layers`,
`kernel_config_validations`, `driver_bundles`, `driver_bundle_kernel_options`,
`driver_bundle_modules`, `driver_bundle_firmware`, `driver_bundle_dt_overlays`,
`external_kernel_modules`, `external_kernel_module_recipes`.
**API:** `GET /v1/kernels/{id}/options`, `.../options/search`,
`.../options/{symbol}`, `POST /v1/kernel-configs/resolve|validate|render|diff|
save-preset`, `POST /v1/driver-bundles`, `POST /v1/external-modules`.
**CLI:** `osfabricumctl kernel options search|show`, `kernel-config
resolve|validate|render|diff|save-preset`, `driver-bundle create`,
`external-module add|build`.
**UI:** Kernel Source · Base Config · Feature Bundles · Hardware Drivers · Raw
Kconfig Search · Config Fragments · Validation · Final Diff.
**Jobs:** `kernel.kconfig.index`, `kernel.config.resolve`,
`kernel.config.validate`, `kernel.config.render`, `kernel.build`,
`kernel.modules.install`, `external-module.fetch`, `external-module.build`,
`external-module.package`, `driver-bundle.resolve`.
**Artifacts:** Kconfig index, final `.config`, config fragments, `modules.alias`,
`modules.dep`, `modules.builtin`, external `.ofpkg` kernel-module packages.
**Tests:** Kconfig index per source/version/arch; symbol search; dependency
display; hidden symbols not treated as checkboxes; options resolved **through**
Kconfig; config hash enters `resolution_hash`; in-tree drivers y/m; external
modules built against the **exact** kernel build tree/config/toolchain; firmware
+ DT overlays attach to bundles.
**Acceptance:** all of the above; `modules.*` captured as artifacts.

### M34 — Filesystem / Image Recipe Designer

**Goal:** Image recipes are data, not hardcoded (closes G-06).
**Output formats:** raw image, qcow2, vmdk, iso, tarball rootfs, update bundle,
sdcard image, usb image, netboot image, container rootfs, VM image.
**Filesystems:** ext4, squashfs, erofs, btrfs, xfs, vfat, overlayfs, tmpfs
mounts, read-only rootfs, A/B partitions, recovery partition, data partition.
**DB:** `image_recipes`, `image_outputs`, `filesystem_profiles`,
`partition_layouts` (extended), `mount_policies`, `overlay_policies`,
`size_policies`.
**API:** `GET/POST /v1/image-recipes`, `POST /v1/image-recipes/{id}/estimate`.
**CLI:** `osfabricumctl image-recipe create|show|estimate`.
**UI:** `/image-recipes`; layout + size estimate shown in M28 step 19.
**Jobs:** `image.compose` (extended, multi-format), `image.estimate`.
**Artifacts:** one or more image outputs per build; size report.
**Tests:** multiple output formats per build; filesystem choice changes the
plan; layout + size estimates rendered.
**Acceptance:** image recipe selectable; no hardcoded sizes/formats in the
pipeline.

### M35 — Package Workspace / Package Manager

**Goal:** Central manager of packages, groups, layers, variants, and cache.
See [`PACKAGE_WORKSPACE.md`](PACKAGE_WORKSPACE.md). Closes G-04, G-28.
**Taxonomy (`package_kinds`):** system, boot, kernel-module, driver, firmware,
runtime, library, service, desktop, application, theme, branding, development,
debug, test, documentation, locale, meta.
**Layers (`package_layers`):** base, hardware, boot, kernel, system, runtime,
services, desktop, applications, branding, development, debug, test.
**DB:** `package_kinds`, `package_layers`, `package_groups`,
`package_group_members`, `package_sets`, `package_set_members`,
`package_variants`, `package_variant_features`, `package_cache_entries`,
`package_compatibility`, `package_locks`, `package_feeds`,
`package_feed_indexes`, `package_promotions`, `package_install_plans`.
**Cache key includes:** package name, version, source hash, recipe hash,
feature hash, arch, libc, toolchain hash, ABI hash, **and** kernel
release/config hash for kernel-bound packages.
**API:** `GET/POST /v1/package-groups`, `.../package-sets`, `.../variants`,
`GET /v1/packages/cache`, `GET /v1/packages/cache/{key}/explain`,
`GET/POST /v1/package-feeds`, `GET/POST /v1/package-locks`.
**CLI:** `osfabricumctl package group|set|variant|cache|feed|lock …`.
**UI:** `/packages`, `/packages/{catalog,groups,sets,cache,feeds,variants,
locks}`; workspace sections: Catalog · Selected for Profile · Groups · Layers ·
Feeds · Build Variants · Cache · Locks · Conflicts · Updates.
**Jobs:** `package.cache.index`, `package.install-plan`, `package.promote`.
**Artifacts:** install plan (`kind=install-plan`), cache index.
**Tests:** group membership; group reuse across distributions; set attached to
profile; system vs application separation; cache namespacing; **cache
hit/miss explained**; kernel-module packages never reused across incompatible
kernel/config/toolchain; install plan artifact.
**Acceptance:** all of the above.

### M36 — Package Feature / Variant Manager

**Goal:** Manage package build options.
**Examples:** busybox applets, cargo features, cmake/meson options, autotools
configure flags, ssl backend, dbus support, init backend (systemd/openrc/
busybox), static/dynamic, plugins.
**DB:** `package_feature_options`, `package_feature_values`,
`package_build_variants`, `package_variant_artifacts`.
**API:** `GET/POST /v1/packages/{id}/features`,
`POST /v1/package-variants/resolve`.
**CLI:** `osfabricumctl package features edit|show`.
**UI:** feature editor in M28 step 12 and `/packages/variants`.
**Jobs:** `package.variant.resolve`, `package.build` (variant-aware).
**Artifacts:** variant artifacts keyed by feature hash.
**Tests:** variant hash includes feature values; resolver knows
feature-dependent deps; variant rebuild on feature change; feature diff visible
in build diff.
**Acceptance:** all of the above.

### M37 — Package Feed / Repository Publisher

**Goal:** Publish signed package feeds for runtime policy and remote devices.
**DB:** `package_feeds`, `feed_indexes`, `feed_signatures`, `feed_channels`,
`feed_publish_jobs`.
**API:** `POST /v1/package-feeds/{id}/publish`, `GET /v1/package-feeds/{id}`.
**CLI:** `osfabricumctl feed publish|show`.
**UI:** `/packages/feeds` shows feed contents.
**Jobs:** `feed.index`, `feed.sign`, `feed.publish`.
**Artifacts:** package index, signatures, package files, kernel-module feed,
firmware feed, application feed, release metadata.
**Tests:** feed generated from promoted artifacts; signed; scoped by
distribution/channel/arch/libc/kernel.
**Acceptance:** runtime package policy can point at a feed; UI shows contents.

### M38 — Runtime Package Policy

**Goal:** Decide whether packages may be installed inside the built OS.
**Policies:** immutable image only, build-time packages only, runtime install
allowed, signed packages only, feed enabled/disabled, writable overlay rootfs,
offline packages only.
**Backends modelled:** none, osf-pkg, opkg-compatible, apk-compatible,
dpkg-compatible, rpm-compatible.
**DB:** `runtime_package_policies`, `runtime_package_backends`.
**API:** policy fields on profile; `GET /v1/runtime-package-backends`.
**CLI:** `osfabricumctl profile runtime-policy set`.
**UI:** policy in M28 step 11/20.
**Jobs:** `runtime-policy.render` (writes package-manager config into rootfs).
**Artifacts:** package-manager config files in the image.
**Tests:** backend choice is profile-level; image receives correct config;
signed-package policy enforced.
**Acceptance:** all of the above.

### M39 — Branding / Identity Designer

**Goal:** Branding as a first-class subsystem (not "just a wallpaper"). See
[`BRANDING_DESIGNER.md`](BRANDING_DESIGNER.md).
**DB:** `branding_profiles`, `branding_assets`, `branding_targets`,
`theme_packages`, `wallpaper_sets`, `boot_splash_themes`,
`login_screen_themes`, `os_release_templates`, `motd_templates`.
**Targets:** bootloader, kernel cmdline splash, initramfs, plymouth, login
manager, desktop session, wallpaper, icon theme, application menu, about dialog,
web UI, terminal motd, `/etc/os-release`, release manifest, installer.
**API:** `GET/POST /v1/branding-profiles`,
`POST /v1/branding-profiles/{id}/render`.
**CLI:** `osfabricumctl branding create|render|attach`.
**UI:** `/branding`; M28 step 18.
**Jobs:** `branding.render`.
**Artifacts:** branding assets, generated `/etc/os-release`, splash/login/
desktop assets, motd.
**Tests:** create; assets are artifacts; attach to distribution/profile;
os-release generated; wallpaper/icon/theme selected; boot/login/desktop branding
targeted separately; branding package belongs to the branding layer.
**Acceptance:** all of the above.

### M40 — Graphical Shell Designer

**Goal:** Manage the GUI stack as a stack, not a checkbox. See
[`GRAPHICAL_SHELL_DESIGNER.md`](GRAPHICAL_SHELL_DESIGNER.md).
**Modes:** no-gui, kiosk, minimal-wayland, weston, labwc, sway, xfce, lxqt,
gnome, kde-plasma, custom-compositor, custom-launcher.
**Fields:** display server, compositor, display manager, greeter, session,
autologin, kiosk app, panel/launcher, notification daemon, settings daemon,
power manager, file manager, terminal, input method, screen lock, accessibility.
**DB:** `graphical_profiles`, `graphical_profile_components`,
`graphical_sessions`.
**API:** `GET/POST /v1/graphical-profiles`,
`POST /v1/graphical-profiles/{id}/expand` (→ package set).
**CLI:** `osfabricumctl graphical create|expand|attach`.
**UI:** `/graphical`; M28 step 16.
**Jobs:** `graphical.expand`, `graphical.render` (session/DM config).
**Artifacts:** session files, display-manager config, autologin config.
**Tests:** attach to profile; stack expands to desktop/runtime packages;
session files generated; autologin configurable; kiosk launches one app; DM
config generated.
**Acceptance:** all of the above.

### M41 — Application Catalog Designer

**Goal:** Manage programs as applications, not only packages.
**DB:** `applications`, `application_versions`, `application_packages`,
`application_desktop_entries`, `application_icons`, `application_mime_handlers`,
`application_autostart`, `application_permissions`, `application_categories`,
`application_defaults`.
**Categories:** browser, terminal, file-manager, editor, office, media-player,
image-viewer, camera, settings, network-tools, development, virtualization,
monitoring, security, kiosk-app, custom-app.
**API:** `GET/POST /v1/applications`, `.../{id}/packages`, `.../{id}/desktop`.
**CLI:** `osfabricumctl application create|map-package|set-default`.
**UI:** `/applications`; M28 step 17.
**Jobs:** `application.resolve`, `application.render-desktop`.
**Artifacts:** `.desktop` entries, icons, MIME handler maps.
**Tests:** app maps to multiple packages; installs `.desktop`; provides icons;
sets MIME handlers; selectable as default; **application package is separate
from system package**.
**Acceptance:** all of the above.

### M42 — Default Applications / Desktop Integration Designer

**Goal:** Manage desktop integration.
**Fields:** default browser/terminal/file-manager/editor/image-viewer/
video-player/PDF-viewer/mail-client, URL handlers, MIME handlers, autostart apps.
**DB:** `desktop_integration_profiles`, `default_handlers`, `autostart_entries`.
**API:** `GET/POST /v1/desktop-integration`,
`POST /v1/desktop-integration/{id}/render`.
**CLI:** `osfabricumctl desktop defaults set|render`.
**UI:** M28 step 17.
**Jobs:** `desktop.render`.
**Artifacts:** `.desktop` files, `mimeapps.list`, icon cache, app-menu
metadata, autostart entries.
**Tests:** defaults saved in profile; entries generated/installed; MIME handlers
generated; icons/themes linked; menu works in the selected shell.
**Acceptance:** all of the above.

### M43 — Theme / Icon / Font Designer

**Goal:** Themes and fonts are first-class packages/assets.
**DB:** `theme_profiles`, `icon_themes`, `cursor_themes`, `gtk_themes`,
`qt_themes`, `font_sets`, `sound_themes`, `wallpaper_sets`.
**API:** `GET/POST /v1/theme-profiles`.
**CLI:** `osfabricumctl theme create|attach`.
**UI:** M28 step 18; `/themes`.
**Jobs:** `theme.resolve`.
**Artifacts:** theme/font packages and asset bundles.
**Tests:** themes are packages/artifacts; theme profile attaches to graphical
profile; font set selectable; theme package belongs to the theme layer; cache
key includes asset hashes.
**Acceptance:** all of the above.

### M44 — Users / Groups / Credentials / Secrets Designer

**Goal:** Manage users and secrets correctly (closes G-09, G-26).
**DB:** `os_users`, `os_groups`, `os_user_groups`, `ssh_authorized_keys`,
`password_policies`, `service_accounts`, `secret_variables`,
`secret_injection_policies`.
**Support:** root locked/unlocked, password login disabled/enabled, SSH keys,
sudo/doas policy, service users, generated host keys, first-boot secret
generation.
**API:** `GET/POST /v1/os-users`, `.../os-groups`, `.../secrets` (write-only
values; never returned in plaintext).
**CLI:** `osfabricumctl user|group|secret …`.
**UI:** M28 step 15 (secrets masked).
**Jobs:** `users.render`, `secrets.inject`, `hostkeys.generate`.
**Artifacts:** `/etc/passwd|group|shadow`, SSH key files, first-boot secret
scripts.
**Tests:** secrets are **not** stored as normal config values; secrets masked
in logs; injected at build or first boot; user/group files generated; SSH keys
installed; service users created.
**Acceptance:** all of the above.

### M45 — Network Designer

**Goal:** Model networking for any class.
**DB:** `network_interfaces`, `network_bridges`, `network_vlans`,
`network_zones`, `firewall_rules`, `dhcp_pools`, `dns_config`, `wifi_profiles`,
`vpn_profiles`.
**Support:** static IP, DHCP client/server, bridge, VLAN, bonding, Wi-Fi
client/AP, firewall, NAT, VPN, DNS, mDNS, IPv6.
**API:** `GET/POST /v1/network-profiles`,
`POST /v1/network-profiles/{id}/render`.
**CLI:** `osfabricumctl network create|render|attach`.
**UI:** M28 step 14; `/network`.
**Jobs:** `network.render`, `network.validate`.
**Artifacts:** init/network-backend-specific config; firewall/NAT rules; Wi-Fi
profiles.
**Tests:** attached to system profile; generator matches selected init/network
backend; firewall/NAT generated; Wi-Fi AP/client generated; validation catches
conflicts.
**Acceptance:** all of the above.

### M46 — Service / Init / Device Manager Designer

**Goal:** Services are not just packages (closes the M11 service-thinness gap).
**Init systems:** busybox init, sysvinit, openrc, runit, s6, systemd, custom.
**Device managers:** static dev, mdev, eudev, systemd-udevd, custom hotplug.
**DB:** `init_systems`, `service_units`, `service_enablement`,
`service_ordering`, `service_healthchecks`, `device_manager_profiles`,
`udev_rules`, `mdev_rules`, `hotplug_scripts`.
**API:** `GET/POST /v1/services`, `.../{id}/order`, `.../{id}/healthcheck`,
`GET/POST /v1/device-managers`.
**CLI:** `osfabricumctl service add|enable|order|healthcheck`,
`device-manager set`.
**UI:** M28 step 13.
**Jobs:** `service.render`, `device-manager.render`.
**Artifacts:** unit/init files, udev/mdev rules, hotplug scripts.
**Tests:** services have enablement state, order/deps, healthchecks; device
manager selected per profile.
**Acceptance:** all of the above.

### M47 — Security / Hardening Designer

**Goal:** Security profile that can enforce and gate.
**Support:** read-only rootfs, no root login, ssh password auth disabled,
firewall default deny, kernel hardening options, sysctl hardening, mount flags
(noexec,nosuid,nodev), service sandboxing, capabilities, seccomp,
apparmor/selinux, audit, secure boot, signed updates.
**DB:** `security_profiles`, `security_rules`, `sysctl_rules`,
`mount_flag_rules`, `security_gates`.
**API:** `GET/POST /v1/security-profiles`,
`POST /v1/security-profiles/{id}/evaluate`.
**CLI:** `osfabricumctl security create|evaluate|attach`.
**UI:** M28 step 21.
**Jobs:** `security.evaluate`, `security.gate`.
**Artifacts:** hardening configs, evaluation report.
**Tests:** attached to profile; can enforce kernel options/sysctl/package
choices; can block insecure configs; **gate runs before release promotion**.
**Acceptance:** all of the above.

### M48 — License / SBOM / Vulnerability / Source Compliance Designer

**Goal:** Compliance is enforceable and gatable.
**DB:** `license_policies`, `license_allowlist`, `license_blocklist`,
`sbom_documents`, `vulnerability_reports`, `source_release_bundles`,
`patch_manifests`, `compliance_gates`.
**Formats:** SPDX, CycloneDX.
**API:** `GET/POST /v1/compliance/policies`, `GET /v1/builds/{id}/sbom`,
`GET /v1/builds/{id}/vulns`, `GET /v1/builds/{id}/source-bundle`.
**CLI:** `osfabricumctl compliance policy|sbom|vulns|source-bundle`.
**UI:** M28 step 22.
**Jobs:** `sbom.generate`, `vuln.scan`, `source.bundle`, `compliance.gate`.
**Artifacts:** SBOM (packages/rootfs/image), source archive, patch list, vuln
report.
**Tests:** SBOM generated; licenses collected; source archive export; patch
list export; vuln result attached; **release blocked by gate**.
**Acceptance:** all of the above.

### M49 — Update / OTA / Recovery Designer

**Goal:** Update strategies and recovery as data.
**Support:** full image update, package update, A/B update, delta update,
recovery image, factory reset, rollback, signed update manifest, channels.
**DB:** `update_strategies`, `update_manifests`, `rollback_policies`,
`recovery_images`, `ota_channels`.
**API:** `GET/POST /v1/update-strategies`,
`POST /v1/builds/{id}/update-bundle`.
**CLI:** `osfabricumctl update strategy|bundle|recovery`.
**UI:** M28 step 20.
**Jobs:** `update.bundle`, `recovery.build`, `update.sign`.
**Artifacts:** update bundle, signed update manifest, recovery image.
**Tests:** strategy selectable; A/B integrates with image recipe; recovery image
generated; rollback policy stored; manifests signed.
**Acceptance:** all of the above.

### M50 — SDK / Dev Shell / Tooling Export

**Goal:** Export a usable SDK from a build plan (closes G-20).
**Outputs:** cross SDK, sysroot, headers, pkg-config files, toolchain env
script, containerized dev shell, debug symbols, gdb config.
**DB:** `sdk_bundles`, `sdk_outputs`.
**API:** `POST /v1/builds/{id}/sdk`, `GET /v1/sdk/{id}`.
**CLI:** `osfabricumctl sdk export|show`.
**UI:** SDK download on the build detail page.
**Jobs:** `sdk.export`, `debug.split`.
**Artifacts:** SDK bundle, sysroot, separated debug symbols.
**Tests:** SDK generated from build plan; sysroot downloadable; debug symbols
separated; dev shell reproduces a package build; SDK hash tied to inputs.
**Acceptance:** all of the above.

### M51 — Cache / Mirrors / Offline Build Designer

**Goal:** Mirrors, offline readiness, pinning (closes G-21).
**Support:** source/package/toolchain mirror, artifact cache, offline mode,
cache warming, cache pinning, mirror priority, checksum verification.
**DB:** `mirrors`, `mirror_priorities`, `cache_pins`, `offline_reports`.
**API:** `GET/POST /v1/mirrors`, `POST /v1/offline-report`,
`POST /v1/cache/warm`, `POST /v1/cache/pin`.
**CLI:** `osfabricumctl mirror add|priority`, `cache warm|pin|report`.
**UI:** `/cache`, `/mirrors`.
**Jobs:** `cache.warm`, `offline.report`, `cache.verify`.
**Artifacts:** offline-readiness report.
**Tests:** offline report works; prefetch plan knows all sources/artifacts;
mirror priority honoured; GC respects pinned artifacts; source cache verifies
checksums.
**Acceptance:** all of the above.

### M52 — QA / Validation Designer

**Goal:** Validation profiles gate promotion (closes G-18 partly, M22 gap).
**Test profiles:** boot test, service health, network test, filesystem test,
package manifest test, security policy test, license gate, SBOM gate,
reproducibility gate, hardware smoke test, serial console capture.
**DB:** `validation_profiles`, `validation_checks`, `validation_results`.
**API:** `GET/POST /v1/validation-profiles`,
`POST /v1/builds/{id}/validate`.
**CLI:** `osfabricumctl validation create|run|attach`.
**UI:** M28 step 23.
**Jobs:** `image.test` (extended), `validation.run`, `serial.capture`.
**Artifacts:** test report (`kind=validation-report`), serial logs.
**Tests:** profile attaches to profile; QEMU + hardware supported; **required
tests block promotion**; report artifact generated.
**Acceptance:** all of the above.

### M53 — Hardware Probe / Import Designer

**Goal:** Turn a probe of real hardware into a board/driver/config draft
(closes G-22).
**Inputs:** `lspci -nn`, `lsusb`, `lsmod`, `modinfo`, `dmesg`,
`/proc/cpuinfo`, `/proc/device-tree`, `/sys/devices/*/modalias`, current
`.config`, `lsblk`, `fstab`.
**DB:** `probe_bundles`, `probe_devices`, `probe_mappings`.
**API:** `POST /v1/probe-bundles`, `GET /v1/probe-bundles/{id}/draft`.
**CLI:** `osfabricumctl probe upload|draft`.
**UI:** `/probe`.
**Jobs:** `probe.parse`, `probe.map-drivers`, `probe.draft-board`,
`probe.draft-config`.
**Artifacts:** board draft, kernel config fragments, suggested driver bundles.
**Tests:** upload bundle; detect devices; map devices→drivers→CONFIG symbols;
map firmware; generate board draft + config fragments.
**Acceptance:** all of the above.

### M54 — Layer / Extension Manager

**Goal:** Yocto/OE-style layers with priority. See
[`LAYER_MODEL.md`](LAYER_MODEL.md).
**Layer types:** core, board/BSP, vendor, distribution, application, branding,
security, local override, private.
**DB:** `layers`, `layer_revisions`, `layer_sources`, `layer_priorities`,
`layer_imports`, `layer_metadata`.
**API:** `GET/POST /v1/layers`, `POST /v1/layers/import`,
`POST /v1/layers/{id}/sync`.
**CLI:** `osfabricumctl layer add|import|sync|priority`.
**UI:** `/layers`, `/distributions/{id}/layers`.
**Jobs:** `layer.import`, `layer.sync`, `layer.index`.
**Artifacts:** layer metadata index; layer revision pin.
**Tests:** Git import; layer holds packages/recipes/configs/profiles/branding/
patches; priority; **layer revision enters the lockfile**; profile uses multiple
layers.
**Acceptance:** all of the above.

### M55 — Priority / Override / Masking Engine

**Goal:** Deterministic override resolution across layers.
**Operations:** priority, override, append, remove, replace, mask, conflict
resolution.
**DB:** `override_rules`, `mask_rules`, `override_results`.
**API:** `POST /v1/overrides/resolve`, `GET /v1/overrides/explain`.
**CLI:** `osfabricumctl override resolve|explain`.
**UI:** override view in `/layers` + explain integration.
**Jobs:** `override.resolve`.
**Artifacts:** resolved-override report.
**Tests:** higher-priority layer overrides lower; masked package/recipe
unavailable; **overrides visible in the explain engine**; conflicts reported
before build.
**Acceptance:** all of the above.

### M56 — Patch Queue / Source Patch Manager

**Goal:** Ordered, recorded source patches.
**DB:** `patch_sets`, `patches`, `patch_targets`, `patch_application_results`.
**Targets:** kernel, package source, branding, config template, build recipe.
**API:** `GET/POST /v1/patch-sets`, `POST /v1/patch-sets/{id}/apply`.
**CLI:** `osfabricumctl patch-set create|apply|show`.
**UI:** `/patches`.
**Jobs:** `patch.apply`.
**Artifacts:** patch application result; failure artifacts.
**Tests:** patch sets ordered; application result stored; failures are
artifacts; applied patches appear in the build plan; source release includes
patches.
**Acceptance:** all of the above.

### M57 — Dependency Graph Viewer

**Goal:** Visualize dependency graphs.
**Graphs:** package, build, runtime, kernel, service, image, layer deps.
**DB:** derived from existing relations (`package_dependencies`,
`artifact_relations`, service ordering, layer priorities).
**API:** `GET /v1/graphs/{kind}?root=…`, `GET /v1/graphs/{kind}/reverse?node=…`.
**CLI:** `osfabricumctl graph show|why|reverse`.
**UI:** `/graphs`; embedded on build/profile pages.
**Jobs:** `graph.compute`.
**Artifacts:** graph JSON.
**Tests:** graph render; "what depends on this?"; "why included?"; conflicts
shown.
**Acceptance:** all of the above.

### M58 — Explain / Why Engine

**Goal:** Every plan item is explainable. See
[`EXPLAIN_ENGINE.md`](EXPLAIN_ENGINE.md). Closes G-19.
**Questions:** why package included? why CONFIG enabled? why firmware/driver
included? why cache miss? why package rebuild? why worker selected? why build
blocked? why release promotion denied?
**DB:** `explain_traces` (or computed + cached per build plan).
**API:** `GET /v1/plan/explain`, `GET /v1/builds/{id}/explain`.
**CLI:** `osfabricumctl explain <item>`.
**UI:** explain popovers throughout the wizard and build detail.
**Jobs:** explain trace emitted during `resolve.plan`.
**Artifacts:** explain trace attached to the build plan.
**Tests:** each plan item has a trace; trace records the source
(manual/profile/group/dependency/driver/security/layer); exposed in UI and CLI.
**Acceptance:** all of the above.

### M59 — Build / Profile / Release Diff

**Goal:** Diff anything (closes G-15).
**Diff types:** package, kernel config, driver, service, filesystem, image
layout, SBOM, vulnerability, artifact hash, size.
**DB:** computed from snapshots; `diff_reports` cache.
**API:** `POST /v1/diff` (profiles | builds | releases).
**CLI:** `osfabricumctl diff profiles|builds|releases <a> <b>`,
`osfabricumctl builds diff <a> <b>` (implements the documented-but-missing
command).
**UI:** `/diff`; profile/build/release compare views.
**Jobs:** `diff.compute`.
**Artifacts:** exportable diff report.
**Tests:** compare two profiles/builds/releases; visible in UI/CLI; exportable.
**Acceptance:** all of the above.

### M60 — System Generations / Rollback Designer

**Goal:** Releases create retained generations with known rollback targets.
**DB:** `generations`, `generation_artifacts`, `rollback_targets`,
`migration_scripts`, `rollback_scripts`.
**API:** `GET /v1/generations`, `POST /v1/generations/{id}/rollback-plan`.
**CLI:** `osfabricumctl generation list|rollback-plan`.
**UI:** `/generations`.
**Jobs:** `generation.create`, `rollback.plan`.
**Artifacts:** generation manifest, rollback plan.
**Tests:** release creates a generation; previous retained; rollback target
known; A/B links to generation; healthcheck failure can trigger a rollback plan.
**Acceptance:** all of the above.

### M61 — Attended Upgrade / Rebuild Service

**Goal:** Rebuild for an existing device/profile while preserving the selected
package set and user choices.
**Inputs:** current generation, target channel/version, current package set,
local overrides, hardware profile, update strategy.
**DB:** `upgrade_requests`, `upgrade_results`.
**API:** `POST /v1/upgrades`, `GET /v1/upgrades/{id}`.
**CLI:** `osfabricumctl upgrade plan|run`.
**UI:** upgrade flow from a generation/device.
**Jobs:** `upgrade.plan`, `upgrade.build`, `upgrade.bundle`.
**Artifacts:** new image, update bundle, diff report, rollback plan.
**Tests:** existing profile rebuilt for a new version; selected packages
preserved; missing/incompatible packages reported; upgrade bundle generated.
**Acceptance:** all of the above.

### M62 — Manifest / Lockfile System

**Goal:** A committable, reproducible `osfabricum.lock`. See
[`LOCKFILE.md`](LOCKFILE.md).
**Lockfile includes:** distribution version, profile version, layer revisions,
package versions, source hashes, toolchain hashes, kernel hashes, config
hashes, artifact refs, build-env hash.
**DB:** `lockfiles`, `lockfile_entries`.
**API:** `POST /v1/plan/lock`, `POST /v1/lock/diff`,
`POST /v1/builds/from-lock`.
**CLI:** `osfabricumctl lock generate|diff|build`.
**UI:** lockfile view on build/profile.
**Jobs:** `lock.generate`, `lock.verify`.
**Artifacts:** `osfabricum.lock`.
**Tests:** generated from build plan; can reproduce the plan; diff works; can
be committed to Git.
**Acceptance:** all of the above.

### M63 — Importers from Competitors / Existing Systems

**Goal:** Bootstrap drafts from existing systems.
**Importers:** Buildroot `.config`, OpenWrt `.config`, Yocto layer metadata,
Debian package list, Alpine package list, NixOS configuration, existing rootfs,
existing image, existing kernel `.config`.
**DB:** `import_jobs`, `import_reports`.
**API:** `POST /v1/imports/{kind}`, `GET /v1/imports/{id}/report`.
**CLI:** `osfabricumctl import buildroot|openwrt|yocto|debian|alpine|nixos|
rootfs|image|kconfig`.
**UI:** `/imports`.
**Jobs:** `import.parse`, `import.map`, `import.draft`.
**Artifacts:** draft distribution/profile, import report.
**Tests:** import creates a draft; imported data is **not trusted blindly**;
report shows mapped vs unknown; user can edit the imported profile.
**Acceptance:** all of the above.

### M64 — Build Analysis Dashboard

**Goal:** Analyze build performance and size. See
[`BUILD_ANALYSIS.md`](BUILD_ANALYSIS.md).
**Reports:** build time, task duration, critical path, package size, image
size, layer usage, recipe usage, warnings/errors, dependency tree, cache
hit/miss.
**DB:** derived from `build_events`/`build_jobs`/artifacts; `build_analyses`
cache.
**API:** `GET /v1/builds/{id}/analysis`.
**CLI:** `osfabricumctl builds analysis <id>`.
**UI:** analysis tab on the build detail page.
**Jobs:** `build.analyze`.
**Artifacts:** analysis report.
**Tests:** slowest jobs visible; largest packages/files visible; cache
efficiency visible; critical path visible.
**Acceptance:** all of the above.

### M65 — Size / Footprint Optimizer

**Goal:** Budgets and footprint reduction.
**Features:** image/rootfs size budgets, largest packages/files, unused
libraries, debug-symbol stripping, locale pruning, docs pruning, static-vs-
dynamic comparison, compression comparison.
**DB:** `size_budgets`, `size_reports`.
**API:** `GET /v1/builds/{id}/size`, `POST /v1/profiles/{id}/size-budget`.
**CLI:** `osfabricumctl size report|budget|suggest`.
**UI:** size tab; budget editor in M28 step 19.
**Jobs:** `size.analyze`, `size.suggest`.
**Artifacts:** size report, suggestions.
**Tests:** budget per profile; build warns/fails on exceed; optimizer suggests
removable packages/files; size diff between builds.
**Acceptance:** all of the above.

### M66 — Boot / Performance Profiler

**Goal:** Profile boot and startup.
**Reports:** boot time, service startup timeline, kernel init timing, userspace
timing, critical path, slow services.
**DB:** `boot_profiles`, `boot_samples`.
**API:** `GET /v1/builds/{id}/boot-profile`.
**CLI:** `osfabricumctl boot-profile <id>`.
**UI:** boot timeline on the build detail page.
**Jobs:** `boot.profile` (QEMU timing / serial capture).
**Artifacts:** boot profile, serial logs.
**Tests:** QEMU boot collects timing; hardware boot collects serial; service
startup report; boot regression visible between builds.
**Acceptance:** all of the above.

### M67 — Distributed Build Farm / Worker Pools

**Goal:** Route jobs to worker pools (extends M5).
**Pools:** local, remote, trusted, untrusted, signing-only, hardware-lab,
qemu-test.
**Features:** worker labels, job affinity, job locality, artifact locality,
remote cache, quotas, parallelism limits.
**DB:** `worker_pools`, `worker_pool_members`, `job_affinities`, `quotas`.
**API:** `GET/POST /v1/worker-pools`, `GET /v1/worker-pools/{id}`.
**CLI:** `osfabricumctl worker-pool create|assign|status`.
**UI:** `/worker-pools`.
**Jobs:** pool-aware routing in the job dispatcher.
**Artifacts:** none new.
**Tests:** jobs target pools; **signing jobs only on trusted/signing**;
hardware tests only on hardware-lab; pool status visible.
**Acceptance:** all of the above.

### M68 — Build Isolation / Sandbox Policy

**Goal:** Declared, enforced build isolation (closes G-25).
**Modes:** none, chroot, bubblewrap, systemd-nspawn, podman/docker, firecracker,
VM.
**Policy fields:** network allowed, write access, cache ro/rw, secret access,
privileged build, allowed mounts, allowed devices.
**DB:** `isolation_policies`, `recipe_isolation_requirements`.
**API:** `GET/POST /v1/isolation-policies`; isolation shown in plan.
**CLI:** `osfabricumctl isolation policy set|show`.
**UI:** isolation shown on recipe/build plan.
**Jobs:** sandbox enforcement wraps `package.build`/`kernel.build`.
**Artifacts:** none new.
**Tests:** recipe declares isolation; **untrusted recipes cannot access
secrets**; network disable for reproducible builds; sandbox policy visible in
the build plan.
**Acceptance:** all of the above.

### M69 — Public Artifact Repository / Release Publishing

**Goal:** Signed public repository + channels (closes G-11, G-27).
**Contents:** images, packages, kernel artifacts, firmware, SBOM, attestations,
release manifests, checksums, signatures.
**DB:** `repositories`, `repository_indexes`, `release` + `release_artifacts`
(wired with CLI/job at last).
**API:** `POST /v1/releases`, `POST /v1/releases/{id}/publish`,
`GET /v1/repositories/{id}`.
**CLI:** `osfabricumctl releases list|show|promote|publish` (implements the
documented-but-missing commands).
**UI:** `/releases`, `/distributions/{id}/releases`, `/repositories`.
**Jobs:** `release.publish`, `repo.index`, `artifact.sign`, `artifact.attest`.
**Artifacts:** repository index, signed manifests, checksums, attached SBOM.
**Tests:** publish creates an index; artifacts signed; checksums published;
SBOM attached; channels supported.
**Acceptance:** all of the above.

### M70 — Documentation Update

**Goal:** Keep docs aligned with the code direction.
**Update or create:** `docs/IMPLEMENTATION_AUDIT.md`, `docs/GAPS.md`,
`docs/NEXT_ACTIONS.md`, `docs/ROADMAP.md`, `docs/OS_BUILDER_WIZARD.md`,
`docs/PACKAGE_WORKSPACE.md`, `docs/KERNEL_DRIVER_DESIGNER.md`,
`docs/BRANDING_DESIGNER.md`, `docs/GRAPHICAL_SHELL_DESIGNER.md`,
`docs/LAYER_MODEL.md`, `docs/EXPLAIN_ENGINE.md`, `docs/LOCKFILE.md`,
`docs/BUILD_ANALYSIS.md`.
**Acceptance:** docs match code direction; no TinyWifi-centric wording;
reference distributions clearly separated from core architecture; every designer
lists DB/API/CLI/UI/jobs/artifacts/tests.

---

## 18c. Core Invariants & Anti-Patterns

These are **forbidden** and must be caught in review/CI. They are the guardrails
that keep OSFabricum a universal OS factory rather than a single-OS builder.

| # | Anti-pattern | Why it is forbidden |
|---|--------------|---------------------|
| 1 | `if distribution == "tinywifi"` | Distributions are data, not code paths. |
| 2 | `if distribution == "netos"` | Same. |
| 3 | `if distribution == "ocultum"` | Same. |
| 4 | Hardcoded package list in the build pipeline | Packages come from profile/package-sets. |
| 5 | Hardcoded kernel config in the build pipeline | Config comes from the Kconfig-resolved fragments. |
| 6 | Hardcoded board firmware in the build pipeline | Firmware comes from the board/BSP model. |
| 7 | Build logic inside the Web UI | UI is a client; it builds nothing. |
| 8 | Package cache key = `name + version + arch` | Must bind source/recipe/feature/libc/toolchain/ABI hashes. |
| 9 | Kernel-module cache without `kernel_release + kernel_config_hash + toolchain_hash` | Modules are ABI-bound to the exact kernel build. |
| 10 | Secret values in logs | Secrets are masked at the worker. |
| 11 | Pretending a documented-only feature is implemented | Status must reflect code + tests. |
| 12 | Mixing system and application packages without taxonomy | Use `package_kinds`/`package_layers`. |
| 13 | Treating branding as only a wallpaper | Branding is a multi-target subsystem. |
| 14 | Treating the graphical shell as a package checkbox | It is a resolved stack. |
| 15 | Treating Kconfig as a static global option list | Kconfig is a typed dependency graph. |

**Current state:** zero distribution-name branches exist in `osfabricum/` and
`apps/` today (verified in `docs/IMPLEMENTATION_AUDIT.md`). This table exists to
keep it that way as the designers land. A CI grep gate for items 1–3 is part of
M24/M25.

## 18d. Tests to Add (M24+)

No test may depend on a reference distribution being the **only** valid
distribution. Coverage to add as the milestones land:

- distribution creation; profile creation; profile inheritance (M25–M27).
- plan generation **with overrides**; build creation from a plan (M29).
- package group resolution; package cache-key generation; kernel-config-hash
  inclusion; driver-bundle resolution (M33, M35, M36).
- branding-profile resolution; graphical-profile package expansion;
  application-default generation (M39–M42).
- layer-override priority; explain-trace generation (M54, M55, M58).
- lockfile generation; build diff generation (M62, M59).

**Test style:** unit tests for the resolver and models; integration tests for
API endpoints; CLI tests for key flows; UI tests where the framework allows.
The first **integration/e2e** suite (closing the empty `tests/integration/` and
`tests/e2e/`) lands with M28 and proves a **non-reference** distribution
end-to-end.

## 20. CLI Reference

### Top-level

osfabricumctl [OPTIONS] COMMAND

Options:
--config PATH     Config file (default: /etc/osfabricum/osfabricum.toml)
--api-url URL     API base URL (default: http://localhost:8000)
--token TOKEN     API auth token (or OSFABRICUM_TOKEN env var)
--output FORMAT   Output format: table, json, yaml (default: table)
--quiet           Suppress progress output
--help            Show help

### build

osfabricumctl build <distribution>/<profile> --board <board>

Start a full build pipeline.

Options:
--board BOARD       Target board (required)
--channel CHANNEL   Target release channel (default: dev)
--follow            Stream logs after submission
--no-test           Skip image.test step
--no-sign           Skip artifact.sign step
--dry-run           Resolve plan only, do not enqueue jobs

Examples:
osfabricumctl build tinywifi/default --board rpi-zero-2w
osfabricumctl build tinywifi/default --board rpi-zero-2w --follow
osfabricumctl build netos/nervum --board qemu-x86_64 --dry-run

### plan

osfabricumctl plan <distribution>/<profile> --board <board>

Resolve and display build plan without building.

Options:
--board BOARD       Target board (required)
--format FORMAT     Output: table, json, yaml
--show-missing      Highlight missing artifacts
--show-jobs         Show required job list

Examples:
osfabricumctl plan tinywifi/default --board rpi-zero-2w
osfabricumctl plan tinywifi/default --board rpi-zero-2w --format json

### prefetch

osfabricumctl prefetch <distribution>/<profile> --board <board>

Download all sources and toolchains for a build plan.

Options:
--board BOARD       Target board (required)
--compliance        Include legal-only sources
--toolchain-only    Fetch toolchain only
--sources-only      Fetch sources only

Examples:
osfabricumctl prefetch tinywifi/default --board rpi-zero-2w
osfabricumctl prefetch tinywifi/default --board rpi-zero-2w --compliance

### builds

osfabricumctl builds list

Options:
--distribution DISTRO
--profile PROFILE
--board BOARD
--status STATUS     (queued, running, completed, failed, cancelled)
--limit N           (default: 20)
--since DATE

osfabricumctl builds show <build_id>

Show full build detail: jobs, artifacts, timings, events.

osfabricumctl builds logs <build_id>

Options:
--job-id JOB_ID     Filter by job
--stream STREAM     stdout or stderr
--follow            Live stream
--since CURSOR      Resume from cursor

osfabricumctl builds cancel <build_id>

osfabricumctl builds reproduce <build_id>

Re-run with same resolution_hash. Report if output sha256 matches.

osfabricumctl builds diff <build_id_1> <build_id_2>

Show differing inputs between two builds.

### package

osfabricumctl package build <name> --arch <arch>

Build a single package.

Options:
--arch ARCH         Target architecture (required)
--version VERSION   Specific version (default: latest)
--force             Rebuild even if artifact cached

osfabricumctl package list

Options:
--arch ARCH
--status STATUS     (built, pending, failed)

osfabricumctl package show <name>

Show package versions, dependencies, artifacts.

osfabricumctl package verify <name> --arch <arch>

Verify stored .ofpkg checksums.

Examples:
osfabricumctl package build nanodhcp --arch aarch64
osfabricumctl package list --arch aarch64 --status built

### kernel

osfabricumctl kernel build <name> --board <board>

Build a kernel for a specific board.

Options:
--board BOARD       Target board (required)
--force             Rebuild even if artifact cached

osfabricumctl kernel list

osfabricumctl kernel show <name>

Examples:
osfabricumctl kernel build linux-rpi --board rpi-zero-2w

### toolchain

osfabricumctl toolchain add <name> --source <source>

Register a toolchain.

Options:
--source SOURCE     bootlin | crosstool-ng | native | path
--version VERSION

osfabricumctl toolchain fetch <name>

Download and store toolchain artifact.

osfabricumctl toolchain verify <name>

Verify stored toolchain sha256.

osfabricumctl toolchain list

Examples:
osfabricumctl toolchain add aarch64-linux-musl --source bootlin
osfabricumctl toolchain fetch aarch64-linux-musl
osfabricumctl toolchain verify aarch64-linux-musl

### artifacts

osfabricumctl artifacts list

Options:
--kind KIND         package, kernel, rootfs, image, sbom, ...
--distribution DISTRO
--board BOARD
--sha256 HASH
--retention-class CLASS
--limit N

osfabricumctl artifacts show <artifact_id>

Show metadata, store_key, sha256, attestations, related artifacts.

osfabricumctl artifacts download <artifact_id> [--output PATH]

osfabricumctl artifacts verify <artifact_id>

Re-verify blob sha256 against stored value.

osfabricumctl artifacts pin <artifact_id>

osfabricumctl artifacts unpin <artifact_id>

### store

osfabricumctl store stats

Show usage per retention class, total bytes, blob count.

osfabricumctl store verify [--artifact ARTIFACT_ID]

Verify all blobs or a specific blob against stored sha256.
Full scan if no artifact specified.

osfabricumctl store gc

Options:
--dry-run           Show what would be deleted
--class CLASS       Limit to retention class
--older-than DURATION   e.g. 14d, 30d

### cache

osfabricumctl cache stats

Show hit/miss ratios per cache type.

osfabricumctl cache verify

Verify cached sources against expected_hash.

osfabricumctl cache gc

Options:
--class CLASS
--older-than DURATION

### workers

osfabricumctl workers list

Show all workers: id, kinds, tags, status, last_seen.

osfabricumctl workers show <worker_id>

Show capabilities, active jobs, heartbeat history.

osfabricumctl workers disable <worker_id>

osfabricumctl workers enable <worker_id>

### flash

osfabricumctl flash list-devices

Show allowlisted flash devices on connected flash workers.

osfabricumctl flash image <artifact_id> --device <device>

Options:
--device DEVICE     Target device path (e.g. /dev/sdX)
--worker WORKER_ID  Target specific flash worker
--verify            Verify after write (default: true)

osfabricumctl flash verify <artifact_id> --device <device>

Verify written media without re-flashing.

### test

osfabricumctl test run <build_id>

Options:
--suite SUITE       Test suite name (default: smoke)
--board BOARD       Override board for QEMU target
--follow            Stream test output

osfabricumctl test list-suites

### catalog

osfabricumctl catalog list distributions
osfabricumctl catalog list profiles [--distribution DISTRO]
osfabricumctl catalog list boards [--arch ARCH]
osfabricumctl catalog list packages [--arch ARCH] [--status STATUS]
osfabricumctl catalog show distribution <name>
osfabricumctl catalog show board <name>
osfabricumctl catalog show profile <distribution>/<profile>

### releases

osfabricumctl releases list [--distribution DISTRO] [--channel CHANNEL]

osfabricumctl releases show <release_id>

osfabricumctl releases promote <build_id>

Options:
--channel CHANNEL   Target channel (dev, staging, stable, lts)
--version VERSION   Release version label

osfabricumctl releases publish <release_id>

---

## 21. Configuration File

Default location: `/etc/osfabricum/osfabricum.toml`
Override: `--config PATH` or `OSFABRICUM_CONFIG` env var.

```toml
[database]
url = "postgresql+asyncpg://osfabricum:password@localhost:5432/osfabricum"
# url = "sqlite+aiosqlite:///./osfabricum-dev.db"  # local dev
pool_size = 10
max_overflow = 20

[store]
root = "/var/lib/osfabricum/store"
work_root = "/var/lib/osfabricum/work"
cache_root = "/var/lib/osfabricum/cache"
# Optional: S3-compatible remote store (post-MVP)
# remote_url = "s3://my-bucket/osfabricum"
# remote_region = "us-east-1"

[queue]
backend = "postgresql"
# pyjobkit settings
prune_after_days = 30
max_attempts_default = 3

[api]
host = "0.0.0.0"
port = 8000
workers = 4
log_level = "info"
# internal queue dashboard
queue_dashboard_path = "/internal/queue"

[auth]
enabled = true
token_header = "Authorization"
# Tokens stored in database, not in config
# Use: osfabricumctl auth create-token --role operator --name ci-bot

[worker]
# Set per worker instance, not globally
worker_id = "worker-aarch64-01"
kinds = ["kernel.build", "package.build", "source.fetch"]
tags = ["arch:aarch64", "cap:qemu"]
max_concurrency = 2
lease_ttl_s = 60
heartbeat_period_s = 10
work_root = "/var/lib/osfabricum/work"
store_mount = "/var/lib/osfabricum/store"

[worker.caches]
sources = "/var/lib/osfabricum/cache/sources"
toolchains = "/var/lib/osfabricum/cache/toolchains"
ccache = "/var/lib/osfabricum/cache/ccache"
package_build = "/var/lib/osfabricum/cache/package-build"

[security]
require_source_hash = true
verify_on_ingest = true
verify_on_use = true
mask_secrets_in_logs = true
# Cosign signing (optional, post-MVP)
# cosign_key_ref = "env://COSIGN_KEY"

[retention]
release = "forever"
promoted = "forever"
staging = "90d"
cache_hot = "30d"
cache_cold = "14d"
failed_run_logs = "30d"
failed_run_blobs = "14d"

[telemetry]
log_format = "json"          # json or pretty
metrics_enabled = true
metrics_path = "/metrics"
otlp_endpoint = ""           # empty = disabled
# otlp_endpoint = "http://localhost:4317"

## 22. Distribution Definition Format
Distributions, profiles, and boards are stored in the database.
They can also be defined in YAML files and imported:

osfabricumctl catalog import --file distributions/tinywifi.yaml

### Distribution File

# distributions/tinywifi.yaml
apiVersion: osfabricum/v1
kind: Distribution
metadata:
  name: tinywifi
  description: Minimal Wi-Fi access point OS
  default_channel: dev

profiles:
  - name: default
    board: rpi-zero-2w
    inherits: null

    arch: aarch64
    libc: musl
    init_system: busybox-init

    toolchain:
      name: aarch64-linux-musl
      source: bootlin

    kernel:
      name: linux-rpi
      version: "6.6.y"
      config: tinywifi-rpi-zero-2w

    packages:
      - name: busybox
        version: "1.36.1"
      - name: dropbear
        version: "2024.85"
      - name: hostapd
        version: "2.10"
      - name: wpa_supplicant
        version: "2.10"
      - name: nftables
        version: "1.0.9"
      - name: nanodhcp
        version: "0.1.0"
      - name: webui-agent
        version: "0.1.0"

    services:
      - name: hostapd
        enabled: true
      - name: nanodhcp
        enabled: true
      - name: webui-agent
        enabled: true
      - name: sshd
        enabled: true

    firmware:
      board: rpi-zero-2w
      blobs:
        - start4.elf
        - fixup4.dat
        - bcm2710-rpi-zero-2-w.dtb

    partition_layout: rpi-2part

    overlays:
      - name: tinywifi-base-overlay

    config_values:
      hostapd:
        ssid: "TinyWifi"
        channel: 6
        hw_mode: g
      nanodhcp:
        interface: wlan0
        range_start: 192.168.4.100
        range_end: 192.168.4.200

    first_boot_tasks:
      - name: generate-hostapd-passwd
        script: scripts/first-boot/generate-passwd.sh

### Board File

# boards/rpi-zero-2w.yaml
apiVersion: osfabricum/v1
kind: Board
metadata:
  name: rpi-zero-2w
  description: Raspberry Pi Zero 2 W

arch: aarch64
soc: bcm2710
boot_scheme: rpi-firmware
firmware_required: true

supported_partition_layouts:
  - rpi-2part
  - rpi-3part

firmware_blobs:
  required:
    - filename: start4.elf
      source: https://github.com/raspberrypi/firmware/raw/stable/boot/start4.elf
      sha256: "..."
      placement: boot
    - filename: fixup4.dat
      source: https://github.com/raspberrypi/firmware/raw/stable/boot/fixup4.dat
      sha256: "..."
      placement: boot
    - filename: bcm2710-rpi-zero-2-w.dtb
      source: kernel
      placement: boot

### Package Recipe File

# packages/nanodhcp/recipe.yaml
apiVersion: osfabricum/v1
kind: PackageRecipe
metadata:
  name: nanodhcp
  version: "0.1.0"
  description: Minimal DHCP server

source:
  type: git
  url: https://github.com/4stm4/nanodhcp
  ref: "26f545d"
  expected_hash: "sha256:..."

build_system: cargo

toolchain:
  target: aarch64-unknown-linux-musl

env:
  CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER: aarch64-linux-musl-gcc
  CARGO_BUILD_INCREMENTAL: "false"
  SOURCE_DATE_EPOCH: "0"

steps:
  prepare: []
  configure: []
  build:
    - cargo build --release --target aarch64-unknown-linux-musl
  install:
    - install -Dm755
        target/aarch64-unknown-linux-musl/release/nanodhcp
        ${DESTDIR}/usr/sbin/nanodhcp
    - install -Dm644
        config/nanodhcp.conf
        ${DESTDIR}/etc/nanodhcp.conf
    - install -Dm755
        init/nanodhcp.init
        ${DESTDIR}/etc/init.d/nanodhcp

runtime_deps: []
build_deps: []
provides:
  - dhcp-server
conflicts: []

licenses:
  - MIT

config_files:
  - /etc/nanodhcp.conf

## 23. Partition Layout Spec
Defined in docs/formats/partition-layout.md and stored in DB as layout_json.

### Schema

{
  "layout_id": "rpi-2part",
  "description": "Raspberry Pi 2-partition layout",
  "partition_table": "mbr",
  "image_size_mb": 512,
  "partitions": [
    {
      "index": 1,
      "label": "boot",
      "type": "fat32",
      "size_mb": 256,
      "mount": "/boot",
      "contents": [
        { "kind": "kernel",   "filename": "kernel8.img" },
        { "kind": "dtb",      "filename": "bcm2710-rpi-zero-2-w.dtb" },
        { "kind": "firmware", "filename": "start4.elf" },
        { "kind": "firmware", "filename": "fixup4.dat" },
        { "kind": "config",   "filename": "config.txt",  "template": "rpi-config" },
        { "kind": "config",   "filename": "cmdline.txt", "template": "rpi-cmdline" }
      ]
    },
    {
      "index": 2,
      "label": "rootfs",
      "type": "ext4",
      "size_mb": -1,
      "mount": "/",
      "contents": [
        { "kind": "rootfs", "source": "rootfs.tar.zst" }
      ]
    }
  ]
}

config.txt template (rpi-config)

arm_64bit=1
kernel=kernel8.img
dtoverlay=disable-bt

cmdline.txt template (rpi-cmdline)

console=serial0,115200 console=tty1 root=/dev/mmcblk0p2
rootfstype=ext4 fsck.repair=yes rootwait quiet

## 24. Channel Promotion Flow
### Channels

nightly  →  dev  →  staging  →  stable  →  lts

| Channel | Purpose | Auto-promoted | Requires |
| nightly | Every successful main branch build | yes | build passes |
| dev | Manually validated nightly | no | operator action |
| staging | Release candidate | no | QEMU tests pass |
| stable | Public release | no | signing + tests |
| --- | --- | --- | --- |
| lts | Long-term support | no | owner action |
### Promotion Rules

nightly → dev
  - Build completed successfully
  - Operator manually promotes

dev → staging
  - QEMU smoke tests pass
  - All artifacts have sha256
  - Operator or CI promotes

staging → stable
  - All tests pass (QEMU + service healthchecks)
  - Image signed with Cosign
  - SBOM generated and signed
  - Release manifest created
  - Owner promotes

stable → lts
  - Active support commitment
  - Owner promotes with explicit LTS version tag

Promotion Commands

# Promote build to dev channel
osfabricumctl releases promote <build_id> --channel dev --version 0.1.0

# Promote to staging (requires tests passed)
osfabricumctl releases promote <build_id> --channel staging

# Publish stable release
osfabricumctl releases publish <release_id>

# View promotion history
osfabricumctl releases list --distribution tinywifi --channel stable

Release Manifest
Stored at:

store/refs/releases/tinywifi/stable/0.1.0/manifest.json

{
  "distribution": "tinywifi",
  "profile": "default",
  "board": "rpi-zero-2w",
  "version": "0.1.0",
  "channel": "stable",
  "resolution_hash": "sha256:...",
  "published_at": "2025-01-01T00:00:00Z",
  "artifacts": [
    {
      "role": "image",
      "name": "tinywifi-rpi-zero-2w.img.zst",
      "artifact_id": "art_01...",
      "sha256": "sha256:...",
      "size_bytes": 134217728
    },
    {
      "role": "sbom",
      "name": "tinywifi-0.1.0.cyclonedx.json",
      "artifact_id": "art_02...",
      "sha256": "sha256:..."
    },
    {
      "role": "signature",
      "name": "cosign.bundle",
      "artifact_id": "art_03...",
      "sha256": "sha256:..."
    }
  ]
}

## 25. Local Development Guide
Requirements
rust

Python 3.13+
PostgreSQL 15+  (or SQLite for minimal local setup)
Docker or Podman  (for worker isolation, optional for dev)
QEMU             (for image.test, optional for dev)

Setup

# 1. Clone
git clone https://github.com/4stm4/osfabricum
cd osfabricum

# 2. Install Python dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Local config (SQLite, no auth)
cp config/osfabricum.dev.toml osfabricum.toml

# 4. Run migrations
alembic upgrade head

# 5. Seed catalog data
osfabricumctl catalog import --file catalog/seed/architectures.yaml
osfabricumctl catalog import --file catalog/seed/boards.yaml
osfabricumctl catalog import --file catalog/seed/distributions.yaml

# 6. Start API
osfabricum-api --config osfabricum.toml

# 7. Start worker (separate terminal)
osfabricum-worker \
  --config osfabricum.toml \
  --worker-id worker-local-01 \
  --kinds source.fetch,toolchain.fetch,resolve.plan \
  --tags arch:x86_64

# 8. Verify
osfabricumctl catalog list distributions
osfabricumctl workers list
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

Minimal dev config (SQLite)

# config/osfabricum.dev.toml
[database]
url = "sqlite+aiosqlite:///./osfabricum-dev.db"

[store]
root = "./dev-store/store"
work_root = "./dev-store/work"
cache_root = "./dev-store/cache"

[queue]
backend = "sqlite"

[api]
host = "127.0.0.1"
port = 8000
log_level = "debug"

[auth]
enabled = false

[security]
require_source_hash = false
verify_on_ingest = true
verify_on_use = true
mask_secrets_in_logs = true

[telemetry]
log_format = "pretty"
metrics_enabled = false

Run unit tests

pytest tests/unit/

Run integration tests (requires PostgreSQL)

docker compose -f tests/docker-compose.yml up -d
pytest tests/integration/
docker compose -f tests/docker-compose.yml down

Build first package locally

# Fetch toolchain
osfabricumctl toolchain add aarch64-linux-musl --source bootlin
osfabricumctl toolchain fetch aarch64-linux-musl

# Build nanodhcp
osfabricumctl package build nanodhcp --arch aarch64

# Verify
osfabricumctl package verify nanodhcp --arch aarch64
osfabricumctl artifacts list --kind package

Run plan (no build)

osfabricumctl plan tinywifi/default --board rpi-zero-2w

## 26. .ofpkg Format Specification

Full spec: `docs/formats/ofpkg.md`

### Structure

<name>-<version>-<arch>.ofpkg     (tar archive, uncompressed outer)
├── manifest.json                  required
├── files.tar.zst                  required (may be empty)
├── checksums.sha256               required
├── scripts/                       optional
│   ├── preinst                    optional, executable
│   ├── postinst                   optional, executable
│   ├── prerm                      optional, executable
│   └── postrm                     optional, executable
└── sbom.json                      required (CycloneDX)

### manifest.json schema

```json
{
  "format": "ofpkg-v1",
  "name": "nanodhcp",
  "version": "0.1.0",
  "arch": "aarch64",
  "libc": "musl",
  "description": "Minimal DHCP server",
  "licenses": ["MIT"],
  "provides": ["dhcp-server"],
  "runtime_deps": [],
  "conflicts": [],
  "replaces": [],
  "config_files": ["/etc/nanodhcp.conf"],
  "files_sha256": "sha256:...",
  "package_sha256": "sha256:...",
  "build_id": "bld_01...",
  "source_ref": "26f545d",
  "source_hash": "sha256:...",
  "toolchain_id": "aarch64-linux-musl-13.2.0",
  "toolchain_sha256": "sha256:...",
  "build_env_hash": "sha256:...",
  "built_at": "2025-01-01T00:00:00Z"
}

checksums.sha256

sha256:<hash>  manifest.json
sha256:<hash>  files.tar.zst
sha256:<hash>  sbom.json
sha256:<hash>  scripts/preinst
sha256:<hash>  scripts/postinst

Script Rules
All scripts must:

Be executable (chmod 755)
Be idempotent
Be non-interactive (no stdin reads)
Exit 0 on success, non-zero on failure
Not modify files outside DESTDIR during build
Not access the network
Script execution order during install:

1. preinst  (before files extracted)
2. files.tar.zst extracted into DESTDIR
3. postinst (after files extracted)

Script execution order during remove:

1. prerm    (before files removed)
2. files removed from rootfs
3. postrm   (after files removed)

Install Process (rootfs.compose step)

for each package in dependency-sorted order:
  1. verify package_sha256
  2. verify files_sha256
  3. verify all checksums.sha256 entries
  4. if scripts/preinst exists → execute in staged rootfs context
## 5. extract files.tar.zst into DESTDIR (staged rootfs)
## 6. if scripts/postinst exists → execute in staged rootfs context
## 7. record installed files list in rootfs manifest
## 8. mark package as installed in build metadata

Config File Handling
Files listed in config_files:

Installed on first install
Never overwritten on reinstall if modified
Marked in rootfs manifest as config-managed
Package Verification

# Verify a stored .ofpkg
osfabricumctl package verify nanodhcp --arch aarch64

# What it checks:
1. Outer archive integrity
2. checksums.sha256 present and parseable
3. sha256(manifest.json) matches checksums entry
4. sha256(files.tar.zst) matches checksums entry
## 5. sha256(sbom.json) matches checksums entry
## 6. manifest.json schema valid
## 7. sbom.json valid CycloneDX
8. package_sha256 in manifest matches computed sha256 of .ofpkg

Naming Convention

<name>-<version>-<arch>.ofpkg

Examples:
  nanodhcp-0.1.0-aarch64.ofpkg
  busybox-1.36.1-aarch64.ofpkg
  hostapd-2.10-aarch64.ofpkg

For packages with libc variant:
  nanodhcp-0.1.0-aarch64-musl.ofpkg
  nanodhcp-0.1.0-aarch64-glibc.ofpkg

## 27. Build System Drivers
Each build system driver implements the same interface:

class BuildDriver(Protocol):
    def prepare(self, ctx: BuildContext) -> None: ...
    def configure(self, ctx: BuildContext) -> None: ...
    def build(self, ctx: BuildContext) -> None: ...
    def install(self, ctx: BuildContext) -> None: ...

BuildContext

@dataclass
class BuildContext:
    work_dir: Path          # Ephemeral build directory
    source_dir: Path        # Extracted source
    destdir: Path           # Staging install root
    toolchain: Toolchain    # Active toolchain
    env: dict[str, str]     # Sanitised build environment
    steps: list[str]        # Commands from recipe
    log_sink: LogSink       # Line-by-line log capture
    arch: str               # Target arch
    libc: str               # Target libc

Base Environment (all drivers)

BASE_ENV = {
    "SOURCE_DATE_EPOCH": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "HOME": "/tmp/build-home",
    "TERM": "dumb",
}

PATH is constructed as:

{toolchain_bin}:{minimal_host_tools_bin}

No access to /usr/local, /opt, or user home directories.

### Cargo Driver

class CargoDriver(BuildDriver):

    def prepare(self, ctx):
        # Write .cargo/config.toml for cross-compilation
        cargo_config = {
            "target": {
                ctx.toolchain.cargo_target: {
                    "linker": ctx.toolchain.cc
                }
            }
        }

    def build(self, ctx):
        env = {
            **BASE_ENV,
            "CARGO_BUILD_INCREMENTAL": "false",
            "CARGO_HOME": str(ctx.work_dir / ".cargo-home"),
            f"CARGO_TARGET_{ctx.toolchain.cargo_target_env}_LINKER":
                ctx.toolchain.cc,
        }
        ctx.run(
            ["cargo", "build", "--release",
             "--target", ctx.toolchain.cargo_target],
            env=env
        )

    def install(self, ctx):
        # Execute install steps from recipe with DESTDIR
        for step in ctx.steps.get("install", []):
            ctx.run_shell(step, env={"DESTDIR": str(ctx.destdir)})

### Make Driver

class MakeDriver(BuildDriver):

    def configure(self, ctx):
        if (ctx.source_dir / "configure").exists():
            ctx.run([
                "./configure",
                f"--host={ctx.toolchain.host_triple}",
                f"--prefix=/usr",
                f"CC={ctx.toolchain.cc}",
                f"CXX={ctx.toolchain.cxx}",
            ] + ctx.steps.get("configure_args", []))

    def build(self, ctx):
        ctx.run([
            "make",
            f"-j{ctx.parallelism}",
            f"CC={ctx.toolchain.cc}",
            f"CXX={ctx.toolchain.cxx}",
            f"CFLAGS={ctx.cflags}",
        ] + ctx.steps.get("build_args", []))

    def install(self, ctx):
        ctx.run([
            "make", "install",
            f"DESTDIR={ctx.destdir}",
        ] + ctx.steps.get("install_args", []))

### CMake Driver

class CMakeDriver(BuildDriver):

    def configure(self, ctx):
        ctx.run([
            "cmake", "-S", ".", "-B", "build",
            f"-DCMAKE_TOOLCHAIN_FILE={ctx.toolchain.cmake_toolchain}",
            f"-DCMAKE_INSTALL_PREFIX=/usr",
            f"-DCMAKE_BUILD_TYPE=Release",
        ] + ctx.steps.get("configure_args", []))

    def build(self, ctx):
        ctx.run([
            "cmake", "--build", "build",
            f"--parallel", str(ctx.parallelism),
        ])

    def install(self, ctx):
        ctx.run([
            "cmake", "--install", "build",
            f"--prefix", str(ctx.destdir / "usr"),
        ])

Custom Driver
When build_system: custom, steps are executed as shell commands
with the full BuildContext environment available:

steps:
  prepare:
    - patch -p1 < patches/fix-musl.patch
  build:
    - ${CC} -O2 -static -o mybin src/main.c
  install:
    - install -Dm755 mybin ${DESTDIR}/usr/bin/mybin

Reproducibility Flags per Driver

REPRO_CFLAGS = [
    "-ffile-prefix-map=/var/lib/osfabricum/work=.",
    "-ffile-prefix-map=./=.",
]

REPRO_LDFLAGS = []

REPRO_CARGO_FLAGS = {
    "CARGO_BUILD_INCREMENTAL": "false",
    "RUSTFLAGS": "--remap-path-prefix /var/lib/osfabricum/work=.",
}

## 28. Base RootFS Builder
What it produces

base-rootfs-aarch64-musl/
├── bin/          → symlink to usr/bin (busybox)
├── sbin/         → symlink to usr/sbin (busybox)
├── lib/          → symlink to usr/lib (musl)
├── usr/
│   ├── bin/      busybox + applets
│   └── lib/      musl libc
├── etc/
│   ├── passwd
│   ├── group
│   ├── shadow
│   ├── shells
│   ├── hostname
│   ├── hosts
│   ├── resolv.conf  (empty stub)
│   ├── inittab      (busybox init)
│   └── profile
├── dev/           (minimal, populated at runtime)
├── proc/          (empty, mounted at runtime)
├── sys/           (empty, mounted at runtime)
├── tmp/           (sticky bit, 1777)
├── run/           (empty)
├── var/
│   ├── log/
│   └── run/ → ../run
└── home/
    └── root/

/etc/passwd (minimal)
ruby

root:x:0:0:root:/home/root:/bin/sh
daemon:x:1:1:daemon:/:/sbin/nologin
nobody:x:65534:65534:nobody:/:/sbin/nologin

/etc/group (minimal)

root:x:0:
daemon:x:1:
nogroup:x:65534:

/etc/inittab (busybox init)
ruby

# Startup
::sysinit:/etc/init.d/rcS

# Serial console
ttyAMA0::respawn:/sbin/getty -L ttyAMA0 115200 vt100

# CTRL-ALT-DEL
::ctrlaltdel:/sbin/reboot

# Shutdown
::shutdown:/etc/init.d/rcK

Build process

1. Fetch busybox source → verify sha256
2. Configure busybox (static, musl, minimal applets)
3. Build busybox with cross toolchain
4. Install busybox into DESTDIR
## 5. Run busybox --install -s to create applet symlinks
## 6. Install musl libc into DESTDIR/usr/lib
## 7. Create /etc skeleton files
## 8. Create directory structure
## 9. Set correct permissions and ownership
## 10. Pack as rootfs-base-aarch64-musl.tar.zst
## 11. Compute sha256, store as artifact
## 12. Record build_env_hash

Busybox Config (TinyWifi minimal)
Applets enabled:

ash, sh, echo, printf, test, [, [[
ls, cp, mv, rm, mkdir, chmod, chown, ln, find, xargs
cat, head, tail, grep, sed, awk
mount, umount, df, du
ifconfig, ip, ping, route
ps, kill, killall, top
getty, login, passwd
init, halt, reboot, poweroff
syslogd, klogd, logread
tar, gzip, zcat
wget, nc

Applets disabled:

vi, nano, less    (save space)
fdisk, mkfs       (not needed in rootfs)
dpkg, rpm         (we use .ofpkg)

## 29. RootFS Composer — Detailed Flow
Input

@dataclass
class RootfsComposeInput:
    base_rootfs_artifact_id: str
    packages: list[PackageRef]     # sorted by dep order
    overlays: list[OverlayRef]
    configs: list[ConfigRef]
    services: list[ServiceRef]
    first_boot_tasks: list[ScriptRef]
    init_system: str               # busybox-init | s6 | runit
    arch: str
    build_id: str

Step-by-step

1. CREATE staging directory
   work/<build_id>/rootfs/

2. EXTRACT base rootfs
   tar -xf base-rootfs-aarch64-musl.tar.zst -C staging/
   → verify extraction integrity

3. INSTALL packages (dependency order)
   for pkg in sorted_packages:
     verify pkg.sha256
     verify pkg.checksums
     execute preinst (if exists)
     tar -xf pkg/files.tar.zst -C staging/
     execute postinst (if exists)
     record installed files → rootfs.manifest

4. APPLY overlays
   for overlay in overlays:
     rsync -av overlay/ staging/
     → deterministic, sorted file order

## 5. RENDER and PLACE configs
   for config in configs:
     rendered = render_template(config.template, config.values)
     write rendered → staging/config.target_path
     mark as config-managed in rootfs.manifest

## 6. INSTALL services
   for service in services:
     if init_system == "busybox-init":
       install service.init_script → staging/etc/init.d/
       chmod 755
       if service.enabled:
         ln -s ../init.d/name staging/etc/rcS.d/S??name

## 7. INSTALL first_boot_tasks
   mkdir -p staging/etc/osfabricum/first-boot.d/
   for task in first_boot_tasks:
     install task.script → staging/etc/osfabricum/first-boot.d/

## 8. GENERATE rootfs.manifest
   {
     "build_id": "...",
     "arch": "aarch64",
     "packages": [{name, version, files: [...]}],
     "config_files": [...],
     "services": [...],
     "generated_at": "..."
   }
   write → staging/etc/osfabricum/rootfs.manifest.json

## 9. PACK rootfs
   tar \
     --sort=name \
     --mtime=@0 \
     --owner=0 \
     --group=0 \
     --numeric-owner \
     -c staging/ | zstd -T0 > rootfs.tar.zst

## 10. COMPUTE sha256(rootfs.tar.zst)

## 11. STORE as artifact
    kind: rootfs
    store_key: rootfs/tinywifi/default/rpi-zero-2w/<build_id>/rootfs.tar.zst
    retention_class: staging

## 12. RECORD in build_events

## 30. Failure Modes and Recovery
Source Fetch Failures
| Failure | Behaviour | Recovery |
| Network timeout | Retry with exponential backoff (max 3) | Auto |
| Hash mismatch | Job fails immediately, source NOT stored | Fix expected_hash in recipe |
| --- | --- | --- |
| 404 Not Found | Job fails, error in build_events | Fix source URI |
| --- | --- | --- |
| VCS ref missing | Job fails, error in build_events | Fix ref in recipe |
| --- | --- | --- |
| Disk full | Job fails, alert metric emitted | Run store.gc |
Package Build Failures
| Failure | Behaviour | Recovery |
| Compile error | Job fails, work dir preserved | Manual: inspect logs, fix recipe |
| --- | --- | --- |
| Missing tool | Job fails with clear error | Add tool to worker, fix recipe |
| --- | --- | --- |
| Toolchain missing | Job fails before compile | Run toolchain.fetch first |
| --- | --- | --- |
| Test failure | Job fails, logs stored | Fix package code or recipe |
| --- | --- | --- |
| Disk full | Job fails | Run store.gc, increase quota |
RootFS Compose Failures
| Failure | Behaviour | Recovery |
| .ofpkg checksum mismatch | Compose fails, rootfs discarded | Rebuild package |
| preinst script fails | Compose fails at that package | Fix script |
| postinst script fails | Compose fails at that package | Fix script |
| Overlay conflict | Compose fails with conflict report | Fix overlay |
| Config template error | Compose fails with template error | Fix template/values |
Worker Failures
| Failure | Behaviour | Recovery |
| Worker crash mid-job | Lease expires, job re-queued | Auto (if retry policy allows) |
| --- | --- | --- |
| Worker offline | Jobs re-queued after lease_ttl | Worker restarts or another claims |
| --- | --- | --- |
| Worker disk full | Job fails, metric emitted | Free space, restart worker |
| --- | --- | --- |
| Heartbeat missed | Worker marked offline after 3× lease_ttl | Investigate worker |
Store Failures
| Failure | Behaviour | Recovery |
| Partial write | Temp file not promoted, ingest fails | Retry ingest |
| Blob sha256 mismatch | store verify reports corruption | Restore from remote or rebuild |
| Disk full | Ingest fails, alert metric | GC or expand storage |
| --- | --- | --- |
| Ref without blob | store verify reports orphan ref | store gc to clean |
Build Recovery Commands

# Retry a failed build
osfabricumctl build tinywifi/default --board rpi-zero-2w

# Retry only failed jobs in an existing build
osfabricumctl builds retry <build_id> --failed-only

# Force rebuild a specific package (ignore cache)
osfabricumctl package build nanodhcp --arch aarch64 --force

# Inspect failed build work directory
osfabricumctl builds show <build_id> --show-work-dirs

# Manually verify all stored artifacts
osfabricumctl store verify

# Verify a specific artifact
osfabricumctl artifacts verify <artifact_id>

## 31. Dependency Resolution Algorithm
### Phase 1 — Collection

1. Start with packages declared in profile
2. For each package, fetch package_version record
3. Fetch runtime_deps for each package_version
4. Recursively collect all transitive deps
## 5. Detect cycles → fail with cycle report

### Phase 2 — Version Selection

For each required package name:
  candidates = package_versions where:
    name matches
    arch matches
    constraint_expr satisfied
    status = 'built' or 'available'

  if len(candidates) == 0:
    add to missing_artifacts
    add package.build job to required_jobs

  if len(candidates) == 1:
    select it

  if len(candidates) > 1:
    select highest version satisfying constraint

### Phase 3 — Conflict Detection

For each selected package:
  check conflicts list against selected set
  if conflict found → fail with conflict report
  check provides list for duplicate virtual packages
  if duplicate → fail unless one replaces the other

### Phase 4 — Sort

Topological sort of dependency graph
→ install order: deps before dependents
→ deterministic: alphabetical within same dep level

### Phase 5 — Output

resolved_packages: [
  {name, version, artifact_id, sha256, install_order}
]
missing_artifacts: [
  {name, version, arch, reason}
]
required_jobs: [
  {kind: "package.build", name, version, arch}
]
conflict_errors: []

Constraint Expression Syntax

">=1.0.0"          at least version
"==1.2.3"          exact version
">=1.0.0,<2.0.0"   range
"*"                any version

MVP: simple string comparison with semver parsing.
Future: SAT solver if constraint complexity grows.

## 32. Kernel Build Process
### Inputs

@dataclass
class KernelBuildInput:
    name: str                    # linux-rpi
    version: str                 # 6.6.y
    arch: str                    # aarch64
    board: str                   # rpi-zero-2w
    source: SourceRef
    config_artifact_id: str      # .config blob
    patches: list[PatchRef]      # in application order
    toolchain: Toolchain

Build Steps

1. FETCH kernel source
   → verify sha256

2. APPLY patches (in declared order)
   for patch in patches:
     patch -p1 < patch.file

3. COPY .config
   cp kernel.config .config

4. OLDDEFCONFIG (update config without prompts)
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-musl- olddefconfig

## 5. VERIFY config applied correctly
   diff .config.expected .config
   → warn on unexpected changes

## 6. BUILD kernel
   make \
     ARCH=arm64 \
     CROSS_COMPILE=aarch64-linux-musl- \
     SOURCE_DATE_EPOCH=0 \
     -j$(nproc) \
     Image modules dtbs

## 7. BUILD modules
   make \
     ARCH=arm64 \
     CROSS_COMPILE=aarch64-linux-musl- \
     INSTALL_MOD_PATH=staging/modules \
     modules_install

## 8. PACK modules
   tar \
     --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
     -C staging/modules \
     -c lib/ | zstd > modules.tar.zst

## 9. COLLECT outputs
   arch/arm64/boot/Image
   modules.tar.zst
   arch/arm64/boot/dts/broadcom/bcm2710-rpi-zero-2-w.dtb

## 10. STORE each as artifact
    kernel/linux-rpi/6.6.y/aarch64/Image           kind=kernel
    kernel/linux-rpi/6.6.y/aarch64/modules.tar.zst kind=kernel-modules
    kernel/linux-rpi/6.6.y/aarch64/*.dtb           kind=dtb

## 11. RECORD config_hash in kernel metadata

Kernel Config Source
For TinyWifi/rpi-zero-2w, the kernel config is stored as an artifact
in the OSFabricum store, referenced by kernel_configs.config_artifact_id.

Config managed via:

# Import a .config file into the store
osfabricumctl kernel import-config \
  --kernel linux-rpi \
  --board rpi-zero-2w \
  --config path/to/.config \
  --name tinywifi-rpi-zero-2w

# Export for editing
osfabricumctl kernel export-config \
  --kernel linux-rpi \
  --board rpi-zero-2w \
  --output .config

# Verify kernel config artifact
osfabricumctl artifacts verify <config_artifact_id>

## 33. Image Composer — Detailed Flow
Input

@dataclass
class ImageComposeInput:
    rootfs_artifact_id: str
    kernel_artifact_id: str
    modules_artifact_id: str
    dtb_artifact_ids: list[str]
    firmware_artifact_ids: list[str]
    partition_layout: PartitionLayout
    board: str
    config_values: dict
    build_id: str

Step-by-step

1. CALCULATE image size
   sum of: partition sizes from layout
   → total_mb = sum(p.size_mb for p in partitions if p.size_mb > 0)
   → dynamic partitions: measure rootfs.tar.zst unpacked + 20% margin

2. CREATE raw image file
   dd if=/dev/zero of=image.raw bs=1M count=<total_mb>

3. CREATE partition table
   if layout.partition_table == "mbr":
     parted -s image.raw mklabel msdos
     parted -s image.raw mkpart primary fat32 1MiB 257MiB
     parted -s image.raw mkpart primary ext4 257MiB 100%
     parted -s image.raw set 1 boot on

4. ATTACH loop device
   losetup --find --show --partscan image.raw
   → /dev/loopX

## 5. FORMAT partitions
   mkfs.vfat -F 32 -n boot /dev/loopXp1
   mkfs.ext4 -L rootfs -E lazy_itable_init=0 /dev/loopXp2

## 6. MOUNT partitions
   mount /dev/loopXp1 mnt/boot/
   mount /dev/loopXp2 mnt/rootfs/

## 7. POPULATE boot partition
   for file in partition[0].contents:
     if file.kind == "kernel":
       cp Image mnt/boot/kernel8.img
     if file.kind == "dtb":
       cp *.dtb mnt/boot/
     if file.kind == "firmware":
       cp firmware_blob mnt/boot/
     if file.kind == "config":
       render_template(file.template, config_values) → mnt/boot/config.txt
       render_template(file.template, config_values) → mnt/boot/cmdline.txt

## 8. POPULATE rootfs partition
   tar -xf rootfs.tar.zst -C mnt/rootfs/
   tar -xf modules.tar.zst -C mnt/rootfs/

## 9. SYNC and UNMOUNT
   sync
   umount mnt/rootfs/
   umount mnt/boot/
   losetup -d /dev/loopX

## 10. COMPRESS image
    zstd -T0 --rm image.raw -o image.img.zst

## 11. COMPUTE sha256(image.img.zst)

## 12. STORE as artifact
    kind: image
    store_key: images/tinywifi/default/rpi-zero-2w/<build_id>/tinywifi.img.zst
    retention_class: staging

## 13. RECORD in build_events

## 34. QEMU Test Runner
Test Execution

@dataclass
class QemuTestInput:
    image_artifact_id: str
    board: str
    arch: str
    test_suite: str
    timeout_s: int = 300

QEMU Command (aarch64 / rpi-zero-2w equivalent)

qemu-system-aarch64 \
  -M virt \
  -cpu cortex-a53 \
  -m 512M \
  -nographic \
  -serial mon:stdio \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -drive file=image.raw,if=virtio,format=raw \
  -kernel kernel8.img \
  -append "root=/dev/vda2 rootfstype=ext4 console=ttyAMA0 rootwait quiet"

Note: For full RPi hardware emulation, board-specific QEMU config
is stored in boards table as qemu_args_json.

Test Suite: tinywifi-smoke

TINYWIFI_SMOKE = [

    Test(
        name="boot-complete",
        description="System reaches login prompt",
        method="serial-expect",
        expect="login:",
        timeout_s=60,
    ),

    Test(
        name="ssh-reachable",
        description="SSH port responds",
        method="tcp-connect",
        port=22,
        timeout_s=30,
    ),

    Test(
        name="hostapd-running",
        description="hostapd process is running",
        method="ssh-command",
        command="pgrep hostapd",
        expect_exit=0,
    ),

    Test(
        name="nanodhcp-running",
        description="nanodhcp service is running",
        method="ssh-command",
        command="pgrep nanodhcp",
        expect_exit=0,
    ),

    Test(
        name="webui-agent-running",
        description="webui-agent service is running",
        method="ssh-command",
        command="pgrep webui-agent",
        expect_exit=0,
    ),

    Test(
        name="sshd-running",
        description="sshd is running",
        method="ssh-command",
        command="pgrep sshd",
        expect_exit=0,
    ),

    Test(
        name="rootfs-manifest-present",
        description="OSFabricum rootfs manifest exists",
        method="ssh-command",
        command="test -f /etc/osfabricum/rootfs.manifest.json",
        expect_exit=0,
    ),

    Test(
        name="package-manifest-check",
        description="All declared packages present in rootfs manifest",
        method="ssh-command",
        command="osfabricum-check-manifest /etc/osfabricum/rootfs.manifest.json",
        expect_exit=0,
    ),

]

Test Results

{
  "suite": "tinywifi-smoke",
  "build_id": "bld_01...",
  "image_artifact_id": "art_01...",
  "started_at": "2025-01-01T00:00:00Z",
  "finished_at": "2025-01-01T00:05:00Z",
  "result": "passed",
  "tests": [
    {"name": "boot-complete",       "result": "passed", "duration_s": 45},
    {"name": "ssh-reachable",       "result": "passed", "duration_s": 2},
    {"name": "hostapd-running",     "result": "passed", "duration_s": 1},
    {"name": "nanodhcp-running",    "result": "passed", "duration_s": 1},
    {"name": "webui-agent-running", "result": "passed", "duration_s": 1},
    {"name": "sshd-running",        "result": "passed", "duration_s": 1},
    {"name": "rootfs-manifest-present", "result": "passed", "duration_s": 1},
    {"name": "package-manifest-check",  "result": "passed", "duration_s": 2}
  ]
}

Test result stored as artifact:

kind: test-result
store_key: tests/tinywifi/default/rpi-zero-2w/<build_id>/tinywifi-smoke.json

## 35. Contributing
Repository Structure

docs/
├── ROADMAP.md            this file
├── ADR/
│   ├── ADR-001.md        NetOS is a distribution
│   ├── ADR-002.md        Toolchain source for MVP
│   └── ...
└── formats/
    ├── ofpkg.md          .ofpkg format spec
    └── partition-layout.md

osfabricum/
├── db/
│   ├── models.py         SQLAlchemy models
│   ├── session.py        async session factory
│   └── migrations/       Alembic versions/
├── jobs/
│   ├── kinds.py          job kind constants
│   ├── executors/
│   │   ├── source_fetch.py
│   │   ├── toolchain_fetch.py
│   │   ├── kernel_build.py
│   │   ├── package_build.py
│   │   ├── rootfs_compose.py
│   │   ├── image_compose.py
│   │   ├── image_test.py
│   │   ├── image_flash.py
│   │   ├── artifact_sign.py
│   │   └── store_gc.py
│   └── router.py         job kind → executor mapping
├── store/
│   ├── blob.py           content-addressed blob storage
│   ├── refs.py           human-readable ref management
│   ├── ingest.py         verify + store pipeline
│   └── gc.py             retention + GC logic
├── resolver/
│   ├── resolver.py       build plan resolution
│   ├── dep_solver.py     dependency graph + sort
│   └── hash.py           resolution_hash computation
├── builder/
│   ├── context.py        BuildContext
│   ├── drivers/
│   │   ├── cargo.py
│   │   ├── make.py
│   │   ├── cmake.py
│   │   ├── meson.py
│   │   └── custom.py
│   └── env.py            build environment construction
├── composer/
│   ├── rootfs.py         rootfs assembly
│   └── image.py          disk image assembly
├── fetcher/
│   ├── source.py         source download + verify
│   └── toolchain.py      toolchain download + verify
├── flasher/
│   └── flash.py          device write + verify
└── schemas/
    ├── api.py            Pydantic API models
    ├── manifest.py       .ofpkg manifest schema
    └── plan.py           build plan schema

### Branching Strategy

main          → stable, always releasable
dev           → integration branch
feature/*     → feature branches, PR to dev
fix/*         → bug fixes, PR to dev or main
release/*     → release preparation

### Commit Convention

feat(resolver): add conflict detection
fix(store): prevent partial blob writes
docs(roadmap): add CLI reference
test(package): add .ofpkg verify tests
chore(deps): upgrade pyjobkit to 0.x.y
build(ci): add QEMU smoke test stage

### PR Requirements

✓ Tests pass (unit + integration)
✓ Type checks pass (mypy --strict)
✓ Lint passes (ruff)
✓ New behaviour has tests
✓ ADR created for architectural decisions
✓ ROADMAP updated if milestone scope changes

## 36. Known Limitations (MVP)
| Limitation | Scope | Future fix |
| --- | --- | --- |
| Single store node only | M3–M23 | Remote store in M8+ |
| No package signing per-package | MVP | M14 introduces signing |
| busybox init only | TinyWifi | s6/runit added for netos/ocultum |
| No multi-arch parallel builds | MVP | M18+ |
| QEMU only for aarch64, no RPi hw | MVP | Hardware-in-loop post M22 |
| No incremental rootfs (full rebuild) | MVP | Optimise post M24 |
| Bootlin prebuilt toolchain only | MVP | crosstool-NG in M6+ |
| No remote workers | MVP | M18+ |
| SQLite not for production queue | Dev only | PostgreSQL required for prod |
| No UI auth in dev mode | Dev config | Auth enabled in prod config |
| Static dep solver (no SAT) | MVP | SAT solver if needed |
