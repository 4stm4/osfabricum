# OSFabricum — Universal OS Builder Wizard

**Milestone:** M28 · **Depends on:** M25 (model), M26 (distribution designer),
M27 (profile designer), M29 (plan/build API).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

The wizard is the single guided path to build **any** class of OS — embedded,
router, server, desktop, kiosk, appliance, mobile-handheld, recovery, firmware,
container-host, hypervisor-host. It is **not** tied to any reference
distribution. The wizard is a pure client: it reads catalog data and writes
through the M29 API. **No build logic lives in the UI.**

---

## Principles

1. **Data in, plan out.** Every step edits records (distribution, profile,
   board, kernel config, package set, …). The wizard never embeds a build
   recipe; it composes a request that the resolver turns into a plan.
2. **Start from anything.** A session can begin from a new distribution, an
   existing distribution, an existing profile, a previous build, or an imported
   image/config (M63).
3. **Plan ≠ build.** The wizard can produce and inspect a build plan without
   enqueuing a single job. Building is an explicit final action.
4. **Explain everywhere.** Every selected package, kernel option, firmware blob,
   and job is annotated with a *why* trace from the Explain Engine (M58).
5. **Draft-safe.** A session is a `build_draft` row; it can be saved, shared by
   URL, and resumed.

---

## Entry & sources

UI entry: `/build/new`. CLI entry: `osfabricumctl build new --from <source>`.

| Start source | Behaviour |
|--------------|-----------|
| New distribution | Creates a draft distribution + first profile. |
| Existing distribution | Lists its profiles; pick or create one. |
| Existing profile | Pre-fills all steps from the profile. |
| Previous build | Clones the build's resolved inputs as a draft profile. |
| Imported image/config | Runs an importer (M63) to seed a draft, flagged "unverified". |

---

## The 25 steps

Each step maps to entities and to the `overrides` accepted by `POST /v1/plan`.

| # | Step | Edits / selects | Backed by |
|---|------|-----------------|-----------|
| 1 | Distribution | distribution (new or existing) | M26 |
| 2 | Profile | profile (new/existing, inherits) | M27 |
| 3 | Distribution class | `distribution_class` | M25 |
| 4 | Board / machine | board + revision | M30 |
| 5 | Architecture / libc | arch, libc policy | M25 |
| 6 | Toolchain | toolchain policy | M6/M25 |
| 7 | Boot chain | boot_scheme / boot chain | M31 |
| 8 | Kernel source / version | kernel | M10/M33 |
| 9 | Kernel options & drivers | kernel_config_fragments, driver_bundles | M33 |
| 10 | Base rootfs | base rootfs policy, init | M15/M46 |
| 11 | Package layers/groups/packages | package_set, package_groups | M35 |
| 12 | Package features | package_features | M36 |
| 13 | Services / init / device manager | service set, init, device manager | M46 |
| 14 | Network | network_profile | M45 |
| 15 | Users / groups / secrets | os_users, secrets | M44 |
| 16 | Graphical shell | graphical_profile | M40 |
| 17 | Applications / default apps | applications, defaults | M41/M42 |
| 18 | Branding / themes / fonts | branding_profile, theme_profile | M39/M43 |
| 19 | Filesystem / image layout | image_recipe, size budget | M34/M65 |
| 20 | Updates / recovery | update_strategy | M49 |
| 21 | Security / hardening | security_profile | M47 |
| 22 | Compliance / SBOM / license | compliance policy | M48 |
| 23 | Validation / tests | validation_profile | M52 |
| 24 | Review build plan | (read-only) plan + explain + cache | M29/M58 |
| 25 | Prefetch / build / test / sign / publish | actions | M29/M37/M69 |

Steps are **non-linear**: any step may be skipped if the profile or class
already supplies a value (e.g. a `no-gui` class hides steps 16–18 unless
overridden). The class chosen in step 3 sets sensible defaults and which steps
are emphasized — but never gates the user from any option.

---

## Step 24 — Review (the heart of the wizard)

The review renders the output of `POST /v1/plan` (no build):

- **Resolution hash** and the inputs that produced it.
- **Missing artifacts** — what must be built/fetched, grouped by job kind.
- **Cache hits/misses** — per package/kernel/toolchain, each with an Explain
  trace for *why a miss* (source changed, recipe changed, feature changed,
  toolchain changed, kernel ABI changed…).
- **Explain** — for every package, kernel CONFIG, firmware blob, and driver:
  source = manual / profile / group / dependency / driver / security / layer.
- **Diff vs. baseline** — optional diff against the source profile/build (M59).
- **Size estimate** — image/rootfs estimate and budget status (M34/M65).

---

## Step 25 — Actions

| Action | API | Result |
|--------|-----|--------|
| Save draft | `PATCH /v1/build-drafts/{id}` | resumable session |
| Build plan | `POST /v1/plan` | plan artifact, no jobs |
| Prefetch | `POST /v1/prefetch` | fetch sources/toolchains |
| Build | `POST /v1/builds` | pyjobkit job graph |
| Test | validation jobs (M52) | validation report |
| Sign | `artifact.sign`/`attest` (M14/M69) | attestations |
| Publish | `POST /v1/releases/{id}/publish` (M69) | repository index |

---

## Data model

- `build_drafts(id, source_kind, source_ref, distribution_id, profile_id,
  board_id, overrides_json, status, created_at, updated_at)`
- A draft references existing entities by id and carries an `overrides_json`
  blob identical in shape to the `POST /v1/plan` `overrides` field, so a draft
  is exactly "a plan request not yet submitted".

## API

`POST /v1/build-drafts`, `PATCH /v1/build-drafts/{id}`,
`GET /v1/build-drafts/{id}`, `DELETE /v1/build-drafts/{id}`; submit via M29.

## CLI

`osfabricumctl build new`, `... build draft save|show|resume`,
`osfabricumctl plan --from-draft <id>`, `osfabricumctl build --from-draft <id>`.

## Worker jobs

The wizard enqueues nothing directly; it delegates to the M29 job graph and to
preview jobs (`profile.resolve-preview`, `image.estimate`, `explain` during
`resolve.plan`).

## Artifacts

Build draft (DB), build plan JSON (`kind=build-plan`), size estimate, explain
trace.

## Tests

- Integration/e2e (first real e2e; closes G-18): wizard → plan → build for a
  **non-reference** distribution of each major class.
- Draft save/resume round-trip.
- Plan-without-build produces a plan artifact and **no** `build_jobs`.
- Review shows cache hit/miss + explain for a known-cached input.

## Acceptance criteria

- Not tied to one OS; starts from distribution/profile/build/image; saves
  drafts; builds a plan without building; creates a build; shows missing
  artifacts, cache hits/misses, and explain for packages/kernel options/jobs.
- **No build logic in the UI** (verified by review: UI only calls the API).
