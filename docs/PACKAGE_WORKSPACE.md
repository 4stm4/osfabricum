# OSFabricum — Package Workspace / Package Manager

**Milestone:** M35 (with M36 variants, M37 feeds, M38 runtime policy).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

The Package Workspace is the central place to organize packages by **kind** and
**layer**, group and reuse them across distributions, attach sets to profiles,
manage build **variants**, and reason about the **cache**. It replaces the
current flat model where `Package.package_type` is a single free string and the
resolver selects *all* package versions for an arch.

---

## Why this exists (gap closed)

Audit finding (G-04, G-28): there is no taxonomy, no layers/groups/sets, no
variants, no feeds, no locks, and the resolver does not select packages per
profile. System packages and application packages are indistinguishable, and
kernel-module packages have no kernel/config/toolchain binding in their
identity. The workspace fixes the **model**; M27/M55 wire it into the resolver.

---

## Taxonomy — `package_kinds`

Every package has exactly one **kind**:

`system`, `boot`, `kernel-module`, `driver`, `firmware`, `runtime`, `library`,
`service`, `desktop`, `application`, `theme`, `branding`, `development`,
`debug`, `test`, `documentation`, `locale`, `meta`.

**Hard rule:** system packages and application packages are never mixed without
this taxonomy. Resolver, install plan, SBOM, and size reports all group by kind.

## Layers — `package_layers`

Every package belongs to one **layer** (ordered, lowest → highest):

`base`, `hardware`, `boot`, `kernel`, `system`, `runtime`, `services`,
`desktop`, `applications`, `branding`, `development`, `debug`, `test`.

Layers give a deterministic install/override order and let the size optimizer
and explain engine attribute footprint and inclusion to a layer.

---

## Data model

| Table | Purpose |
|-------|---------|
| `package_kinds` | the 18 kinds above (seed data) |
| `package_layers` | the 13 layers above (seed data, ordered) |
| `package_groups` | named, reusable bundles of packages |
| `package_group_members` | group ↔ package(+version constraint) |
| `package_sets` | a resolved selection attachable to a profile |
| `package_set_members` | set ↔ group / package |
| `package_variants` | a package built with specific features |
| `package_variant_features` | variant ↔ feature value |
| `package_cache_entries` | cache key → artifact |
| `package_compatibility` | which variants are ABI/kernel compatible |
| `package_locks` | pinned versions for reproducibility |
| `package_feeds` | published runtime feeds (M37) |
| `package_feed_indexes` | feed contents/index |
| `package_promotions` | staging → promoted transitions |
| `package_install_plans` | the ordered install plan artifact record |

`packages.package_type` is migrated to `package_kind_id` + `package_layer_id`
(data-preserving migration; default `system`/`system`).

---

## Cache keys (closes G-28)

A package cache key is **forbidden** from being `name + version + arch`. The key
MUST include:

```
package name
package version
source hash
recipe hash
feature hash          (M36 variant features)
arch
libc
toolchain hash
ABI hash
+ for kernel-bound packages (kind ∈ {kernel-module, driver}):
    kernel release
    kernel config hash
```

Consequences enforced by `package_compatibility`:

- A `kernel-module`/`driver` package is **never** reused across an incompatible
  kernel release / config / toolchain. A different `.config` ⇒ a different key
  ⇒ a rebuild.
- A feature change (M36) changes `feature hash` ⇒ a new variant ⇒ a rebuild.
- Every cache hit/miss is **explained** (M58): the key field that differs is
  reported.

---

## Package Workspace UI

Pages: `/packages`, `/packages/catalog`, `/packages/groups`,
`/packages/sets`, `/packages/cache`, `/packages/feeds`, `/packages/variants`,
`/packages/locks`.

Workspace sections (one screen, tabbed): **Catalog · Selected for Profile ·
Package Groups · Package Layers · Repositories / Feeds · Build Variants · Cache ·
Locks · Conflicts · Updates**.

## API

`GET/POST /v1/package-groups`, `.../package-sets`, `.../variants`;
`GET /v1/packages/cache`, `GET /v1/packages/cache/{key}/explain`;
`GET/POST /v1/package-feeds`; `GET/POST /v1/package-locks`;
`POST /v1/package-sets/{id}/resolve` (→ install plan).

## CLI

`osfabricumctl package group create|add|reuse`,
`osfabricumctl package set create|attach`,
`osfabricumctl package variant define`,
`osfabricumctl package cache stats|explain <key>`,
`osfabricumctl feed publish`, `osfabricumctl package lock generate`.

## Worker jobs

`package.cache.index`, `package.install-plan`, `package.promote`,
`package.variant.resolve`, `package.build` (variant- and key-aware),
`feed.index` / `feed.sign` / `feed.publish` (M37).

## Artifacts

- `install plan` (`kind=install-plan`) — ordered, per-profile, dependency-sorted.
- cache index; feed index + signatures (M37).

## Tests

- Packages added to groups; **groups reused between distributions**.
- Package set attached to a profile; resolver uses it (two profiles → two sets).
- System vs application separation enforced by kind.
- Runtime/desktop/theme/branding/development/test kinds separated.
- Cache namespaced by arch/libc/toolchain/kernel/profile where needed.
- **Cache hit/miss explained** (key-diff reported).
- Kernel-module packages never reused across incompatible kernel/config/
  toolchain (compatibility test).
- Install plan generated as an artifact.

## Acceptance criteria

All of the above. The workspace is the data source the resolver (M27/M55)
consumes; no package selection is hardcoded in the pipeline.
