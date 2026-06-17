# OSFabricum — Manifest / Lockfile System

**Milestone:** M62 ✅ Done · **Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

**Implementation status:** `osfabricum/lockfile/service.py`. Tables:
`lockfiles` (distribution_id/profile_id/build_id FK SET NULL, lock_version,
rendered_lock, content_hash) and `lockfile_entries` (lockfile_id CASCADE,
entry_kind, entry_key, version, source_hash; upsert by lockfile+kind+key).
Entry kinds: package|kernel|toolchain|config|layer|source|artifact|build-env.
`render_lockfile` produces [meta]+[kind] INI + sha256:… hash.
`diff_lockfiles(a_id, b_id)` returns `{added, removed, changed}` dicts.
API: `POST /v1/lockfiles`, `GET /v1/lockfiles`, `POST /v1/lockfiles/{id}/render`,
`POST /v1/lockfiles/diff`. CLI: `osfabricumctl lockfile generate/render/diff/list`.
UI: `/lockfile` page (4 tabs). 21 unit tests.

`osfabricum.lock` is a committable, human-diffable manifest that pins every
input to a build plan so the plan can be reproduced exactly — on another machine,
in CI, or months later. It is the reproducibility contract on top of the
`resolution_hash`.

---

## What the lockfile pins

```
distribution version
profile version
layer revisions          (each selected layer → exact revision)
package versions         (every package in the resolved set)
source hashes            (every fetched source → sha256)
toolchain hashes         (toolchain artifact identities)
kernel hashes            (kernel source + build identity)
config hashes            (final kernel .config + rendered config hashes)
artifact refs            (store keys of inputs already built)
build env hash           (the reproducibility env spec, see ROADMAP §12)
```

Because the lockfile carries the same inputs that feed `resolution_hash`, a lock
re-resolves to the same hash; a differing hash means an input drifted, and the
lock diff shows exactly which.

## Format

`osfabricum.lock` is deterministic, sorted, and text-diffable (YAML/TOML with
stable key order). It lives at the repository root next to the distribution/
profile YAML it locks, and is meant to be committed to Git.

```yaml
apiVersion: osfabricum/v1
kind: Lockfile
distribution: { name: <n>, version: <v> }
profile:      { name: <n>, version: <v> }
layers:
  - { name: core,   revision: <git-sha> }
  - { name: vendor, revision: <git-sha> }
packages:
  - { name: <n>, version: <v>, variant_hash: <h>, source_hash: <h>, artifact: <store-key> }
toolchains:
  - { name: <n>, hash: <h>, artifact: <store-key> }
kernel:       { name: <n>, source_hash: <h>, config_hash: <h>, artifact: <store-key> }
build_env_hash: <h>
resolution_hash: sha256:<...>
```

## Data model

`lockfiles(id, distribution_id, profile_id, resolution_hash, content_artifact_id,
created_at)`; `lockfile_entries(lockfile_id, entry_kind, name, version, hash,
artifact_ref)`.

## API

`POST /v1/plan/lock` (generate a lock from a plan request),
`POST /v1/lock/diff` (diff two locks),
`POST /v1/builds/from-lock` (build exactly what a lock pins).

## CLI

`osfabricumctl lock generate` (→ `osfabricum.lock`),
`osfabricumctl lock diff <a> <b>`,
`osfabricumctl lock build` (build from a committed lock),
`osfabricumctl lock verify` (does the current catalog still match the lock?).

## UI

Lockfile view on the build and profile pages; download `osfabricum.lock`; lock
diff rendered alongside build diff (M59).

## Worker jobs

`lock.generate` (emitted from a resolved plan), `lock.verify`.

## Artifacts

`osfabricum.lock` (`kind=lockfile`).

## Tests

- Lockfile generated from a build plan.
- Lockfile can **reproduce** the plan (same `resolution_hash`).
- Lockfile **diff** works (drifted input identified).
- Lockfile can be committed to Git (deterministic, stable ordering).

## Acceptance criteria

All of the above. The lockfile + layers (M54) make a build portable: a
collaborator clones the repo, runs `osfabricumctl lock build`, and gets the same
artifacts — with no distribution-specific code involved.
