# OSFabricum

> A data-driven build factory for Linux-based operating systems, firmware, and bootable images.

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue.svg)

OSFabricum builds many **classes** of operating system — embedded, router,
server, desktop, kiosk, appliance, mobile/handheld, recovery, firmware,
container-host, hypervisor-host — from a single data-driven core.

It is **not** a Buildroot/Yocto wrapper or a web UI over a legacy build system.
It is an independent OS build factory driven by a database registry of
distributions, boards, kernels, packages and image recipes.

> **Key decision:** *No distribution is a backend. Every distribution is a set
> of records managed by OSFabricum.* There are no `if distribution == "..."`
> branches in the core — a new OS is new data, not new code.

Reference distributions (validation profiles, **not** architecture):
`tinywifi` (router/embedded), `netos` (infrastructure/SDN), `ocultum`
(mobile/handheld).

---

## Architecture

OSFabricum is three processes over one database:

| Process | Entry point | Role |
| --- | --- | --- |
| **API** | `osfabricum-api` | FastAPI app: read/write registry, designers, dashboard, job queue |
| **Worker** | `osfabricum-worker` | Pulls build jobs from the `pyjobkit` queue and runs the pipeline |
| **CLI** | `osfabricumctl` | Operator CLI: plan/build, and a thin client over every designer |

Everything is data. Distributions, profiles, boards/BSPs, boot chains,
initramfs profiles, kernels (as a typed Kconfig graph), image recipes and
packages are DB records resolved into a deterministic build plan with a content
hash, dispatched to the queue, and built into signed, verifiable artifacts.

**Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · Typer ·
`pyjobkit` queue · uvicorn · SQLite by default (PostgreSQL optional).

---

## Designers (web UI)

The API serves a dark-themed dashboard and a designer page per domain. Each page
is a thin client over the public `/v1` write API.

| Route | Designer | What it models |
| --- | --- | --- |
| `/` | Dashboard | builds, artifacts, distributions, boards, workers |
| `/distributions` | Distribution Designer | distributions, classes, channels |
| `/profiles` | Profile Designer | profiles, inputs, package sets, versioning |
| `/build/new` | Build Wizard | self-contained build flow with prefetch |
| `/boards` | Board / BSP Designer | boards as BSPs (SoC, firmware, DT, flash) |
| `/boot-chains` | Boot Chain Designer | U-Boot/GRUB/EFI/RPi/PXE boot artifacts |
| `/initramfs` | Initramfs Designer | initramfs profiles + early modules |
| `/kernel-config` | Kernel / Driver Designer | Kconfig as a typed dependency graph, driver bundles |
| `/image-recipes` | Image Recipe Designer | output formats, filesystems, partition layouts, size policy |
| `/packages` | Package Workspace | kind/layer taxonomy, groups/sets, cache, variants, locks |

---

## Quick start

Requires Python ≥ 3.12.

```bash
# install (editable, with dev extras)
pip install -e '.[dev]'

# create / migrate the database (default: ./osfabricum-dev.db)
alembic upgrade head

# run the API + dashboard at http://127.0.0.1:8000
osfabricum-api

# (in another shell) run a worker to process build jobs
osfabricum-worker
```

Open <http://127.0.0.1:8000> for the dashboard, or explore the API at
`/docs` (OpenAPI).

### Seed the reference catalog

A fresh database has only the fixed enumerations seeded by the migrations. To
load the bundled reference catalog (architectures, boards, kernels, toolchains,
distributions, …):

```bash
# import catalog YAML (architectures first — boards/kernels reference them)
for f in architectures boards sources toolchains kernels distributions; do
  osfabricumctl catalog import -f "catalog/seed/$f.yaml"
done

# load BSP / boot-chain / initramfs designer seed data
osfabricumctl board seed
osfabricumctl bootchain seed
osfabricumctl initramfs seed
```

### Build from the CLI

The seed loads distributions but not profiles — create one (or use the Profile
Designer at `/profiles`):

```bash
osfabricumctl profile create tinywifi default
```

```bash
# resolve a build plan without building
osfabricumctl plan tinywifi/default --board rpi-zero-2w

# report what a plan would need to fetch (sources/toolchains/packages)
osfabricumctl prefetch tinywifi/default --board rpi-zero-2w

# run the full pipeline (plan → rootfs → image)
osfabricumctl build tinywifi/default --board rpi-zero-2w --store-root ./_store
```

---

## CLI overview

`osfabricumctl --help` lists the full surface. Highlights:

- **Build:** `build`, `plan`, `prefetch`
- **Catalog & registry:** `catalog`, `distribution`, `profile`, `builds`, `artifacts`, `workers`
- **Designers:**
  - `board`, `bootchain`, `initramfs`
  - `kerneldesign` — index a Kconfig graph, `resolve`/`render` a `.config`, driver bundles
  - `imagedesign` — filesystem profiles, partition layouts, size policies, `estimate`
  - `packageworkspace` — kind/layer taxonomy, cache keys (`cache-lookup` explains a miss), groups/sets, `set-resolve`, `feature-define`/`variant-resolve`, locks
- **Packaging & lower levels:** `package`, `kernel`, `firmware`, `toolchain`, `rootfs`, `source`, `store`, `image`, `flash`, `test`

The CLI reads `OSF_DATABASE_URL` / `OSFABRICUM_DB_URL` for a one-off DB override;
otherwise it uses the configured database.

---

## Project layout

```
osfabricum/            core library (data-driven, distribution-agnostic)
  db/                  SQLAlchemy models, sessions, seed data
  resolver/            build-plan resolution + content hashing
  pipeline/            build coordinator (plan → rootfs → image)
  board/ bootchain/    BSP, boot chain and early-boot designers
  initramfs/
  kerneldesign/        Kconfig dependency graph + driver bundles (M33)
  imagedesign/         image recipes, partition layouts, size estimator (M34)
  packageworkspace/    package taxonomy, cache keys, variants (M35/M36)
  store/ queue/ ...     artifact store, job queue, repro, security, fetch
apps/
  api/                 FastAPI app, routes, static designer pages
  worker/              queue worker
  cli/                 osfabricumctl
migrations/            Alembic migration chain (head: 0012)
catalog/               seed data (boards, boot chains, …)
docs/                  roadmap, gap audit, designer specs, ADRs
tests/                 unit + integration tests
```

---

## Development

```bash
ruff format .          # format
ruff check .           # lint
mypy osfabricum apps   # type-check
pytest -q              # run the test suite
```

The Alembic chain is guarded so `alembic upgrade head` runs cleanly on a fresh
database and `upgrade → downgrade` round-trips; a test enforces that the migrated
schema matches the ORM models.

---

## Documentation

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — milestones and the universal OS builder model
- [`docs/IMPLEMENTATION_AUDIT.md`](docs/IMPLEMENTATION_AUDIT.md) — vertical audit of what exists
- [`docs/GAPS.md`](docs/GAPS.md) — gap register and per-gap status
- Designer specs: [`KERNEL_DRIVER_DESIGNER`](docs/KERNEL_DRIVER_DESIGNER.md),
  [`PACKAGE_WORKSPACE`](docs/PACKAGE_WORKSPACE.md),
  [`BSP_DESIGNER`](docs/BSP_DESIGNER.md), [`OS_BUILDER_WIZARD`](docs/OS_BUILDER_WIZARD.md), …

---

## License

[AGPL-3.0-or-later](LICENSE) © 4STM4
