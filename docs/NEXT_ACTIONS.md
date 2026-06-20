# OSFabricum — Next Actions

**Revision:** 2026-06 (updated M70)
**Source:** `docs/IMPLEMENTATION_AUDIT.md` + `docs/GAPS.md`.
**Rule:** Do **not** restart M0–M23. Every action below assumes the existing
primitives stay and are extended. No "temporary stub", no "minimal first".
Each action names the milestone that owns it and the gap it closes.

> **Status as of 2026-06-20:** Phase 4 (M24–M69) and Phase 5 (M71–M73) are
> **complete**. All milestones shipped their full vertical (DB → migration →
> service → API → CLI → UI → tests). M70 and M74 (Documentation Updates)
> also complete. Gaps G-01 through G-22 and G-25 are closed. Reference
> distributions (TinyWifi/NetOS/Ocultum) are seeded as pure data records with
> 39 unit tests passing. **Next up: A1–A4 (foundation for user-created
> distributions, profile-aware resolver, write API).**

---

## Ordering principle

The dependency order is forced by three structural gaps (G-01 write API, G-02
resolver, G-03 job graph). Until those move, designers have nowhere to persist
to, nothing to resolve from, and no way to build. So the sequence is:

1. **Foundation of "create"** — universal model + write API + profile-aware
   resolver (M24 → M29). ✅ Done.
2. **Hardware & boot** (M30 → M34). ✅ Done.
3. **Packages, kernel, branding, shell, apps** (M33, M35 → M43). ✅ Done.
4. **System concerns** — users, network, services, security, compliance,
   updates, SDK, cache, QA, probe (M44 → M53). ✅ Done.
5. **Competitive layer** — layers, overrides, patches, graph, explain, diff,
   generations, upgrade, lockfile, importers, analysis, size, boot, farm,
   sandbox, repo (M54 → M69). ✅ Done.
6. **Docs** (M70). ✅ Done.
7. **Phase 5 — Reference Distributions** (M71–M73). ✅ Done.
8. **Foundation for user-created distributions** (A1–A4). ← current horizon.

---

## Immediate queue (closes structural gaps)

### A1 — Land the universal data model (M25) → closes nothing yet, unblocks all
- Add entities: `distribution_class`, `profile` (expanded), `board` (expanded),
  `package_set`/`package_group`, `boot_scheme`, `image_recipe`,
  `branding_profile`, `graphical_profile`, `network_profile`,
  `security_profile`, `update_strategy`, `validation_profile`.
- Add `distribution_class` enum: embedded, router, server, desktop, kiosk,
  appliance, mobile-handheld, recovery, firmware, container-host,
  hypervisor-host.
- Migration with **explicit DDL** (also retro-fix G-23: stop relying on
  `metadata.create_all` for new tables).
- Acceptance: a distribution + profile can be created with class/board/kernel/
  packages/branding/UI/services/image-layout **as data**, with no code path per
  name.

### A2 — Profile-aware resolver (M27 + M35) → closes G-02
- Wire `_merged_inputs` into selection: packages come from the profile's
  package set(s)/groups, not "all for arch". Toolchain/kernel come from profile
  policy, not "first for arch".
- Consult `package_dependencies` for a topological install order.
- Emit a per-item **explain trace** stub (source: manual/profile/group/
  dependency/driver/security/layer) for M58.
- Acceptance: two profiles on the same arch resolve to **different** package
  sets; same inputs → same `resolution_hash`.

### A3 — Write API: distributions, profiles, plan, prefetch, builds (M26/M27/M29) → closes G-01, G-03, G-13, G-14
- `POST/PATCH/DELETE /v1/distributions`, `clone`, `import`, `export`.
- `POST/PATCH /v1/profiles`, `clone`, `diff`, `versions`.
- `POST /v1/plan`, `POST /v1/plan/validate`, `POST /v1/plan/diff` (read model →
  write model: accept `overrides`).
- `POST /v1/prefetch`.
- `POST /v1/builds` (dispatches a **pyjobkit job graph**, not in-process),
  `/rebuild`, `/clone-as-profile`.
- Enforce auth on all write endpoints (closes G-24).
- Expose `osfabricumctl build` and `osfabricumctl prefetch` verbs.
- Acceptance: a build can be created from API/CLI/UI; `package.build` runs as a
  job; status flows through events/logs; cancel works.

### A4 — Build Wizard (M28) → closes G-17, starts G-18
- 25-step wizard UI driving the write API; can start from distribution,
  profile, previous build, or imported image; saves drafts; shows missing
  artifacts, cache hits/misses, and explain.
- First **integration/e2e** test that drives wizard → plan → build for a
  non-reference distribution.

---

## Per-gap action table

| Gap | Action | Milestone |
|-----|--------|-----------|
| G-01 write API | Build write endpoints + auth | M26, M27, M29 |
| G-02 resolver | Profile inputs → selection; dep sort; explain stub | M27, M35, M55, M57, M58 |
| G-03 job graph | Build API → pyjobkit graph; `package.build` as job | M29, M67, M68 |
| G-04 packages | Taxonomy, layers, groups, sets, variants, feeds, locks, cache | M35, M36, M37, M38 |
| G-05 kernel | Kconfig index, fragments, validation, driver bundles, ext modules | M33 |
| G-06 image | Image-recipe entity, multi-format, A/B, size policy | M34 |
| G-07 branding/UI/apps | Branding, graphical, app catalog, defaults, themes | M39–M43 |
| G-08 boards | Board/BSP, boot chain, initramfs designers | M30, M31, M32 |
| G-09 secrets/users | Users/groups/credentials/secrets designer | M44 |
| G-10 net/svc/sec/comp | Network, service-init, security, compliance designers | M45–M48 |
| G-11 releases/OTA | ~~Update/OTA/recovery, generations, upgrade, repo~~ | **✅ M49+M60+M61+M69** |
| G-12 competitive | ~~Layers, overrides, patch, graph, explain, diff, lockfile, importers, analysis, size, boot~~ | **✅ M54–M66** |
| G-13 prefetch CLI | ~~`osfabricumctl prefetch` from plan~~ | **✅ M29** |
| G-14 build CLI | ~~`osfabricumctl build` verb~~ | **✅ M29** |
| G-15 diff/reproduce | ~~Implement `builds diff` / `builds reproduce`~~ | **✅ M59** |
| G-16 releases CLI | ~~`osfabricumctl releases …` + promotion flow~~ | **✅ M69** |
| G-17 UI read-only | ~~Designers + wizard UI~~ | **✅ M26–M28+** |
| G-18 no e2e | ~~Integration/e2e harness~~ | **✅ M52** |
| G-19 explain | ~~Explain/why engine~~ | **✅ M58** |
| G-20 SDK | ~~SDK / dev-shell export~~ | **✅ M50** |
| G-21 cache/mirror | ~~Cache/mirror/offline designer~~ | **✅ M51** |
| G-22 probe | ~~Hardware probe import~~ | **✅ M53** |
| G-23 migrations | Explicit DDL + CI drift check | M24, M25 (partial) |
| G-24 auth | Enforce auth on write API | M29 (partial — `require_write_auth` dep on writes) |
| G-25 sandbox | ~~Build isolation/sandbox policy~~ | **✅ M68** |
| G-26 secret mask | Secret masking model + tests | M44 |
| G-27 signing e2e | Exercise signing/attestation in release flow | M48, M69 (partial) |
| G-28 cache keys | Strong package/kernel-module cache keys | M35 |

---

## Tests to add (carried into the milestones above)

No test may depend on a reference distribution being the **only** valid
distribution. Required new coverage:

- distribution creation; profile creation; profile inheritance.
- plan generation **with overrides**; build creation from a plan.
- package group resolution; package cache-key generation; kernel-config-hash
  inclusion; driver-bundle resolution.
- branding-profile resolution; graphical-profile package expansion;
  application-default generation.
- layer-override priority; explain-trace generation; lockfile generation; build
  diff generation.

Style: unit tests for resolver/models; integration tests for API endpoints; CLI
tests for key flows; UI tests where the framework allows.

---

## Definition of "the next work is unblocked"

When A1–A4 are merged:

- A new OS (not TinyWifi/NetOS/Ocultum) can be created and built from the UI and
  CLI through the write API.
- The resolver differentiates profiles by their declared data.
- Builds run as a job graph on workers.
- The first e2e test proves a non-reference distribution end-to-end.

At that point the designer milestones (M30+) can land independently and in
parallel, each closing one S2/S3 gap, without re-touching M0–M23.
