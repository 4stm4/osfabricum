# OSFabricum — Layer / Extension Model

**Milestones:** M54 (layers), M55 (priority/override/masking), M56 (patch queue).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

OSFabricum separates **build metadata** from **layers**, in the spirit of
Yocto/OpenEmbedded: a layer is an independently-versioned, prioritized
collection of metadata (packages, recipes, configs, profiles, branding,
patches) that composes with other layers. Higher-priority layers can override,
append to, remove, replace, or mask lower-priority metadata, deterministically.

---

## Layer types

`core`, `board/BSP`, `vendor`, `distribution`, `application`, `branding`,
`security`, `local override`, `private`.

A distribution selects an **ordered list of layers**. Reference distributions
are themselves expressed as a `distribution` layer over `core` — never as code.

## Data model (M54)

| Table | Purpose |
|-------|---------|
| `layers` | id, name, type, description |
| `layer_revisions` | pinned revision (commit/tag) of a layer source |
| `layer_sources` | Git/URL source of a layer |
| `layer_priorities` | per-distribution priority ordering |
| `layer_imports` | import jobs + status |
| `layer_metadata` | what a layer contributes (packages/recipes/configs/profiles/branding/patches) |

A layer can contribute: packages, build recipes, config templates, profiles,
branding profiles, and patch sets. A `layer_revision` is recorded in the
lockfile ([`LOCKFILE.md`](LOCKFILE.md)).

## Override / masking engine (M55)

Operations, applied highest-priority-first:

| Op | Meaning |
|----|---------|
| `priority` | establish ordering between layers |
| `override` | replace a metadata value from a lower layer |
| `append` | add to a list-valued metadata field |
| `remove` | drop an entry contributed by a lower layer |
| `replace` | swap one recipe/package for another |
| `mask` | make a package/recipe **unavailable** entirely |
| `conflict resolution` | report and resolve conflicting contributions |

The resolved result is recorded and **every override is visible in the Explain
Engine** ([`EXPLAIN_ENGINE.md`](EXPLAIN_ENGINE.md)): "package X comes from layer
`vendor` (priority 50), overriding `core` (priority 10)". Conflicts are reported
**before** a build starts, never silently.

Tables: `override_rules`, `mask_rules`, `override_results`.

## Patch queue (M56)

Ordered source patches, with recorded results.

Tables: `patch_sets`, `patches`, `patch_targets`, `patch_application_results`.
Targets: `kernel`, `package source`, `branding`, `config template`,
`build recipe`. Patch sets have an order; application results (success/failure)
are stored; failures are artifacts; applied patches appear in the build plan and
in the source release bundle (M48).

## API

`GET/POST /v1/layers`, `POST /v1/layers/import`, `POST /v1/layers/{id}/sync`,
`GET /v1/layers/{id}`; `POST /v1/overrides/resolve`,
`GET /v1/overrides/explain`; `GET/POST /v1/patch-sets`,
`POST /v1/patch-sets/{id}/apply`.

## CLI

`osfabricumctl layer add|import|sync|priority|show`,
`osfabricumctl override resolve|explain`,
`osfabricumctl patch-set create|apply|show`.

## UI

`/layers`, `/distributions/{id}/layers` (ordering + priorities),
`/patches`; override results shown inline with Explain.

## Worker jobs

`layer.import`, `layer.sync`, `layer.index`; `override.resolve`;
`patch.apply`.

## Artifacts

Layer metadata index; layer revision pin (→ lockfile); resolved-override
report; patch application results.

## Tests

- Layers imported from Git; can contain packages/recipes/configs/profiles/
  branding/patches.
- Layers have priority; **layer revision enters the lockfile**.
- Profile uses multiple layers.
- Higher-priority layer overrides lower-priority metadata.
- Masked package/recipe is unavailable.
- **Overrides visible in the Explain Engine.**
- Conflicts reported before build.
- Patch sets ordered; results stored; failures are artifacts; applied patches
  appear in the build plan.

## Acceptance criteria

All of the above. Layers are how customization scales without code paths: a new
vendor/board/distribution is a layer + data, never an `if` in the pipeline.
