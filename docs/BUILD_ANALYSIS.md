# OSFabricum — Build Analysis

**Milestones:** M64 (analysis dashboard), M65 (size optimizer), M66 (boot
profiler), drawing on M59 (diff) and M58 (explain).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

Build Analysis turns the data OSFabricum already records — `build_events`,
`build_jobs`, artifacts, sizes, cache outcomes — into actionable reports:
where time went, where bytes went, and where boot time went.

---

## M64 — Build Analysis Dashboard

**Reports:** build time, task duration, **critical path**, package size, image
size, layer usage, recipe usage, warnings/errors, dependency tree, cache
hit/miss.

Computed from existing rows (no new instrumentation needed for timing/cache):

- **Critical path** — longest dependency chain through the job graph (M29),
  derived from `build_jobs` start/end times + dependency edges.
- **Slowest jobs** — `build_jobs` ranked by duration.
- **Largest packages/files** — from artifact sizes + install plan (M35).
- **Cache efficiency** — hit/miss ratio with per-miss explanation (M58).
- **Layer/recipe usage** — which layers/recipes contributed how much.

**API:** `GET /v1/builds/{id}/analysis`. **CLI:** `osfabricumctl builds analysis
<id>`. **UI:** an Analysis tab on the build detail page. **Job:**
`build.analyze`. **Artifact:** analysis report.

**Acceptance:** the build detail page shows slowest jobs, largest packages/
files, cache efficiency, and the critical path.

---

## M65 — Size / Footprint Optimizer

**Features:** image size budget, rootfs size budget, largest packages, largest
files, unused libraries, debug-symbol stripping, locale pruning, docs pruning,
static-vs-dynamic comparison, compression comparison.

- A **size budget** is set per profile; a build **warns or fails** when the
  budget is exceeded.
- The optimizer **suggests** removable packages/files (unused libs, docs,
  locales, debug symbols) with the estimated saving and the explain trace for
  why each is present.
- **Size diff** between two builds reuses the diff engine (M59).

**DB:** `size_budgets`, `size_reports`. **API:** `GET /v1/builds/{id}/size`,
`POST /v1/profiles/{id}/size-budget`. **CLI:** `osfabricumctl size
report|budget|suggest`. **UI:** Size tab + budget editor in Wizard step 19.
**Jobs:** `size.analyze`, `size.suggest`. **Artifacts:** size report,
suggestions.

**Acceptance:** budget per profile; build warns/fails on exceed; optimizer
suggests removals; size diff works between builds.

---

## M66 — Boot / Performance Profiler

**Reports:** boot time, **service startup timeline**, kernel init timing,
userspace timing, critical path, slow services.

- QEMU boot (M52 test harness) collects timing; hardware boot collects serial
  logs (M30 board test methods, M67 hardware-lab pool).
- A **service startup report** orders services by start time and flags slow
  units (uses M46 service ordering/healthchecks).
- **Boot regression** is visible between builds (timeline diff).

**DB:** `boot_profiles`, `boot_samples`. **API:**
`GET /v1/builds/{id}/boot-profile`. **CLI:** `osfabricumctl boot-profile <id>`.
**UI:** boot timeline on the build detail page. **Job:** `boot.profile`.
**Artifacts:** boot profile, serial logs.

**Acceptance:** QEMU boot collects timing; hardware boot collects serial;
service startup report generated; boot regression visible between builds.

---

## How the three compose

All three analyses share the same substrate and cross-link:

- **Time** (M64/M66) and **size** (M65) reports both hang off a build and both
  support **diff** against another build (M59).
- Every "why is this big / slow / present?" answer routes through the **Explain
  Engine** (M58) — e.g. a large package's inclusion is attributed to a profile,
  group, dependency, driver bundle, or layer.
- Budgets (M65) and required validations (M52) can **gate promotion** (M69):
  a build over budget or with a boot regression can block a stable release.

## Tests

- Analysis: slowest jobs, largest packages/files, cache efficiency, critical
  path all rendered.
- Size: budget enforced (warn/fail); suggestions produced; size diff between
  builds.
- Boot: timing collected under QEMU; serial captured on hardware; regression
  visible between builds.

## Acceptance criteria

All of the above, with every metric traceable to data via the Explain Engine and
comparable via the Diff engine — no analysis depends on a specific (reference)
distribution.
