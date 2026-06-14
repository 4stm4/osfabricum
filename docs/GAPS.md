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
- **Status: ◑ Resolved (M35 part; G-28 closed).** Packages now have a `kind`
  (18 seeded kinds) and `layer` (13 ordered layers) — system and application
  packages are distinguishable and the install plan groups by kind/layer.
  Groups are reusable across distributions; sets attach to a profile and
  `resolve_set` produces a deterministic, layer-ordered install plan record.
  **G-28 is closed:** `compute_cache_key` forbids `name+version+arch` and folds
  in source/recipe/feature/toolchain/ABI hashes — and, for `kernel-module`/
  `driver` kinds, the kernel release + config hash (required, else error). A
  different `.config` ⇒ a different key ⇒ a rebuild; every hit/miss is explained
  by the differing field (`lookup_cache`/`explain_cache`), with a queryable
  `package_compatibility` record. Locks/feeds/promotions/variants are modelled.
  Exposed over `/v1/package-*` + `/v1/packages/cache*`, the `osfabricumctl
  packageworkspace` CLI and the `/packages` workspace page.
- **M36 (features/variants) done.** Packages declare typed feature options
  (`bool`/`choice`/`string`/`int`) with allowed values that pull in
  feature-dependent deps. `resolve_variant` validates a requested feature set,
  fills defaults, collects the implied deps and computes a deterministic
  `feature_hash` — which **is** the M35 cache-key `feature_hash` component, so a
  feature change yields a new variant hash ⇒ new cache key ⇒ rebuild; the
  feature diff is reported by `diff_variants`. Exposed over
  `GET/POST /v1/packages/{id}/features`, `POST /v1/package-variants/resolve`,
  the `osfabricumctl packageworkspace feature-*/variant-resolve` CLI and the
  `/packages` Variants tab.
- **M37 (feed publisher) done.** Feeds are now signed and scoped. Three new
  tables — `feed_signatures`, `feed_channels`, `feed_publish_jobs` — extend the
  M35 feed skeleton. `publish_feed` walks the ordered index, computes a
  deterministic `sha256:` content hash (same pattern as `plan_hash`), stores a
  `FeedSignature` and a `FeedPublishJob` with status `done`. Feeds can be
  scoped by `distribution/arch/libc/kernel_release` via `FeedChannel` rows.
  `get_feed` returns the full feed: index entries, scope rules and the latest
  signature. Exposed over `GET /v1/package-feeds/{id}`,
  `POST /v1/package-feeds/{id}/publish`, `POST /v1/package-feeds/{id}/scope`,
  the `osfabricumctl feed list|create|show|index-add|scope|promote|publish` CLI
  and the `/packages` Feeds tab. Follow-on: asymmetric signing (M48), feed
  *serve/mirror* endpoint and OTA client integration (M49).
- **M38 (runtime package policy) done.** Seven policies (`immutable` /
  `build-time` / `runtime-install` / `signed-only` / `feed-enabled` /
  `overlay-rootfs` / `offline-only`) govern whether a PM is baked into the
  image and what it may install. Six backends (`none` / `osf-pkg` / `opkg` /
  `apk` / `dpkg` / `rpm`) are seeded at migration time. `set_policy` validates
  the policy/backend combination and upserts a `RuntimePackagePolicy` keyed by
  `profile_id`. `render_policy` expands the backend's `config_template` against
  attached M37 feeds and stores the rendered text deterministically. Exposed
  over `GET /v1/runtime-package-backends`,
  `GET/POST /v1/profiles/{dist}/{name}/runtime-policy`,
  `POST /v1/profiles/{dist}/{name}/runtime-policy/render`, the
  `osfabricumctl profile runtime-policy|runtime-policy-set|runtime-policy-render|runtime-backends`
  CLI and a Policy drawer in the `/profiles` designer. Follow-on: feeding
  the rendered config into the rootfs compose step (M46/pipeline).

### G-05 — Kernel config is an opaque blob, not a Kconfig model
- **Evidence:** `KernelConfig` references a `config_artifact_id` blob. No Kconfig
  symbol index (types, `depends on`, `select`, `imply`, `choice`, prompts,
  defaults). No driver bundles, no external-module recipes.
- **Impact:** Kernel options cannot be presented or validated; "checkbox"
  configs would be wrong (Kconfig is a typed dependency graph, not a flat list).
  Kernel-module packages have no kernel/config/toolchain binding.
- **Closed by:** **M33** (Kernel/Driver Designer: Kconfig index, fragments,
  validation, driver bundles, external modules, captured `modules.*`).
- **Status: ✅ Resolved (model + resolver).** Kconfig is now a typed symbol graph
  (`kernel_option_symbols` with type, prompt/hidden, `depends`/`select`/`imply`
  edges in `kernel_option_dependencies`). `resolve_config` type-checks, rejects
  hidden symbols, forces `select` targets on, applies `imply` softly, and fails a
  requested symbol whose `depends on` is unmet — never a flat checkbox list.
  `render_config` emits `.config` text with a deterministic `sha256:` hash;
  driver bundles (options/modules/firmware/DT overlays) and external-module
  recipes are modelled and resolvable. Exposed over `/v1/kconfig-indexes`,
  `/v1/kernel-configs/*`, `/v1/driver-bundles`, `/v1/external-modules`, the
  `osfabricumctl kerneldesign` CLI and the `/kernel-config` designer page.
  Follow-ons: parsing a real kernel source tree into the index and executing
  external-module builds (the ingest contract and recipe steps exist; the
  job/runner wiring lands with the kernel build jobs).

### G-06 — No image-recipe model (single raw format, hardcoded sizes)
- **Evidence:** `osfabricum/image/composer.py` produces raw `.img` only; sizes
  are hardcoded defaults in the pipeline (`boot_size_mb=4`, `rootfs_size_mb=16`).
- **Impact:** No qcow2/vmdk/iso/squashfs/erofs/btrfs/A-B/recovery/container
  outputs; no per-profile filesystem/layout selection; no size policy.
- **Closed by:** **M34** (Filesystem / Image Recipe Designer).
- **Status: ✅ Resolved (model + estimator).** Output images are data now:
  `image_recipes` ties a reusable `partition_layouts` (normalized into
  `partition_entries`), `filesystem_profiles`, `size_policies`, `image_outputs`
  (multi-format per build), `mount_policies` and `overlay_policies`.
  `estimate_recipe` walks the layout, validates the role set (exactly one
  `rootfs`, or a matched `ab_a`/`ab_b` pair) and applies the size policy
  (alignment, reserve, free-space %, grow-to-fit) to produce a deterministic
  partition-size plan with a `sha256:` hash — replacing the hardcoded
  `boot_size_mb` / `rootfs_size_mb` constants. Exposed over
  `/v1/image-recipes`, `/v1/filesystem-profiles`, `/v1/size-policies`,
  `/v1/partition-layouts`, the `osfabricumctl imagedesign` CLI and the
  `/image-recipes` designer page. Follow-on: wiring the multi-format *compose
  execution* (qcow2/iso/squashfs/erofs/…) into `image.compose` and feeding the
  estimate into the live pipeline's `resolution_hash` (the model and estimator
  the pipeline reads from are in place).

### G-07 — Branding, graphical shell, applications are not modelled
- **Evidence:** No tables/services for branding profiles/assets, graphical
  stacks, application catalog, desktop integration, themes/fonts.
- **Impact:** Desktop/kiosk/appliance distribution classes are unbuildable
  beyond raw packages; branding is not first-class; "graphical shell" cannot be
  selected as a stack.
- **Closed by:** **M39** (branding), **M40** (graphical shell), **M41**
  (application catalog), **M42** (default apps/desktop integration), **M43**
  (themes/icons/fonts).
- **Status: ✅ Resolved (M39–M43 done).** All five designer modules are
  implemented end-to-end (models → migration → service → API → CLI → UI →
  tests). Follow-on: users / groups / credentials / secrets (M44).
- **M39 (branding / identity designer) done.** `BrandingProfile` is extended
  with 11 OS-release identity fields (`os_name`, `os_id`, `os_version`,
  `os_pretty_name`, `os_home_url`, `vendor_name`, `vendor_url`, `support_url`,
  `bug_report_url`, `logo_asset_id`, `icon_asset_id`) plus rendered-artifact
  columns. Seven new tables: `branding_assets` (logo/icon/favicon/wallpaper/
  splash/login-bg/font/sound), `branding_targets` (one row per build stage —
  bootloader / plymouth / initramfs / login-screen / desktop-session /
  os-release / motd / about-dialog / web-ui / installer), `os_release_templates`,
  `motd_templates`, `wallpaper_sets`, `boot_splash_themes`, `login_screen_themes`.
  `render_os_release` generates deterministic `/etc/os-release` content from
  profile identity fields with a `sha256:` content hash (same convention as
  `plan_hash`/`index_hash`); a custom Python `{field}`-format template is
  supported via `OsReleaseTemplate`. `render_motd` renders from `MotdTemplate`
  or falls back to a default welcome string. Migration `0015_branding_designer`
  extends `branding_profiles` with per-column guards and uses a `fresh` sentinel
  for the 7 new tables. Exposed over 13 HTTP endpoints under
  `/v1/branding-profiles/…`, the `osfabricumctl branding` CLI and the
  `/branding` designer UI page (7 tabs: Profiles, Assets, Stage Targets, Boot
  Splash, Login Theme, OS-Release, MOTD). 32 unit tests. Follow-on:
  graphical-shell (M40), application catalog (M41) — both done.
- **M40 (graphical shell designer) done.** `GraphicalProfile` extended with 10
  new columns: `display_server` (none/x11/wayland/both), `compositor`,
  `display_manager`, `session_manager`, `toolkit_default`,
  `rendered_session_config`, `content_hash`, `rendered_at`, `created_at`,
  `updated_at`. Four new tables: `compositor_backends` (seeded — 10 entries:
  none/mutter/kwin/sway/labwc/hyprland/openbox/xfwm4/marco/icewm),
  `display_manager_backends` (seeded — 6 entries:
  none/gdm/lightdm/sddm/greetd/ly), `graphical_components` (packages bound by
  21 kinds: compositor/window-manager/desktop-shell/panel/bar/…), and
  `graphical_sessions` (selectable `[Desktop Entry]` sessions). `add_component`
  validates kinds; `add_session` auto-generates the `.desktop` text. 
  `render_session_config` generates a deterministic `[Desktop Entry]` for the
  default session (or a named placeholder), stores a `sha256:` content hash.
  `update_graphical_profile` clears the rendered cache. Migration
  `0016_graphical_shell` uses per-column guards and a `fresh` sentinel; seeds 10
  + 6 backends idempotently. Exposed over 10 HTTP endpoints under
  `/v1/graphical-profiles/…`, `/v1/compositor-backends`,
  `/v1/display-manager-backends`, the `osfabricumctl graphical` CLI and the
  `/graphical` designer UI page (6 tabs: Profiles, Compositors, Display
  Managers, Components, Sessions, Render). 36 unit tests. Follow-on:
  application catalog (M41).
- **M41 (application catalog designer) done.** Five new tables:
  `app_categories` (seeded — 11 entries: productivity/internet/multimedia/
  graphics/office/development/games/utilities/system/education/accessibility),
  `app_catalog_profiles` (per-distribution catalog with render columns),
  `catalog_apps` (name/display_name/package_name/category/version_constraint/
  icon/is_default_install/is_optional/tags), `app_groups` (named collections),
  `app_group_members` (bridge with position), `default_app_roles` (MIME/
  functional role → app binding; 14 valid roles: web-browser/text-editor/
  file-manager/terminal/email-client/music-player/video-player/image-viewer/
  pdf-viewer/archive-manager/calculator/calendar/contacts/camera).
  `render_app_list` generates a deterministic INI `[Catalog]`/`[App:*]`/
  `[Group:*]`/`[Role:*]` manifest with a `sha256:` content hash; stores result
  on the profile row. `set_default_role` is an upsert. Migration
  `0017_app_catalog` uses a `fresh` sentinel and seeds 11 categories idempotently.
  Exposed over 10 HTTP endpoints under `/v1/app-catalog-profiles/…` +
  `/v1/app-categories`, the `osfabricumctl appcatalog` CLI (category-list/
  list/create/show/update/app-add/group-add/member-add/role-set/render) and
  the `/appcatalog` designer UI page (6 tabs: Profiles, Categories, Apps,
  Groups, Default Roles, Render). 39 unit tests, all passing. Follow-on:
  default apps / desktop integration (M42) — done.
- **M42 (desktop integration designer) done.** Five new tables:
  `mime_type_definitions` (seeded — 21 entries: text/html/plain/x-python/
  x-shellscript/markdown, image/jpeg/png/gif/webp/svg+xml, audio/mpeg/ogg/
  flac, video/mp4/webm/x-matroska, application/pdf/zip/x-tar/
  x-7z-compressed, inode/directory), `desktop_integration_profiles`
  (xdg_data_dirs/xdg_config_dirs/rendered_mimeapps/rendered_user_dirs/
  content_hash/rendered_at), `mime_associations` (mime_type → desktop_file
  with association_type: default|added|removed and priority),
  `autostart_entries` (exec_cmd/condition: always|graphical|wayland|x11/
  is_enabled; auto-generates XDG `[Desktop Entry]` text with OnlyShowIn
  for non-always conditions), `xdg_user_dirs` (upsert by dir_name:
  DESKTOP/DOWNLOAD/DOCUMENTS/MUSIC/PICTURES/VIDEOS/TEMPLATES/PUBLICSHARE).
  `render_desktop_integration` generates `/etc/xdg/mimeapps.list`
  (`[Default Applications]`, `[Added Associations]`, `[Removed Associations]`
  sections) and `/etc/xdg/user-dirs.defaults` (8 dirs with fallback defaults),
  concatenates both for a `sha256:` content hash. `set_user_dir` is an upsert.
  Migration `0018_desktop_integration` uses a `fresh` sentinel and seeds
  21 MIME type definitions idempotently. Exposed over 9 HTTP endpoints under
  `/v1/desktop-integration-profiles/…` + `/v1/mime-types`, the
  `osfabricumctl desktopint` CLI (mime-list/list/create/show/update/mime-add/
  autostart-add/userdir-set/render) and the `/desktopint` designer UI page
  (6 tabs: Profiles, MIME Types, MIME Associations, Autostart, User Dirs,
  Render). 44 unit tests, all passing. Follow-on: themes/icons/fonts (M43).
- **M43 (themes / icons / fonts designer) done.** Four new tables:
  `theme_asset_kinds` (seeded — 6 entries: gtk-theme/icon-theme/cursor-theme/
  sound-theme/font-face/wallpaper), `theme_profiles` (gtk_theme/icon_theme/
  cursor_theme/sound_theme, dark_mode, font_default/font_monospace/font_document,
  font_size, cursor_size, scaling_factor, rendered_gsettings/rendered_gtk_ini/
  content_hash/rendered_at), `theme_packages` (profile_id → asset_kind +
  package_name + version_constraint + is_default; unique per profile+kind+pkg),
  `gsettings_overrides` (profile_id → schema + key + value; upsert pattern).
  `render_theme_config` generates a dconf override file (`[org/gnome/desktop/
  interface]` section with gtk-theme/icon-theme/cursor-theme/font-name/
  monospace-font-name/text-scaling-factor/color-scheme, optional `[org/gnome/
  desktop/sound]` for non-freedesktop themes, plus user-supplied gsettings
  overrides grouped by schema) and a GTK `settings.ini` ([Settings] block).
  Both concatenated for a `sha256:` content hash; `update_theme_profile` clears
  the cache. `add_theme_package` validates against VALID_ASSET_KINDS.
  `set_gsettings_override` is an upsert. Migration `0019_theme_designer` uses a
  `fresh` sentinel and seeds 6 asset kinds idempotently. Exposed over 9 HTTP
  endpoints under `/v1/theme-profiles/…` + `/v1/theme-asset-kinds`, the
  `osfabricumctl theme` CLI (kind-list/list/create/show/update/pkg-add/
  gsetting-set/render) and the `/theme` designer UI page (5 tabs: Profiles,
  Asset Kinds, Packages, GSettings, Render). 37 unit tests, all passing.
  Follow-on: users / groups / credentials / secrets (M44).

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
