# OSFabricum — Explain / Why Engine

**Milestone:** M58 (with M57 dependency graph).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

Every decision the resolver and scheduler make must be answerable with a
**why**. The Explain Engine attaches a trace to every build-plan item so a user
can ask "why is this here?" and get a precise, sourced answer in the UI and CLI.

---

## Why this exists (gap closed)

Audit finding (G-19): the resolver emits flat lists (`packages`,
`missing_artifacts`, `required_jobs`) with no provenance. With layers (M54),
overrides (M55), driver bundles (M33), and security enforcement (M47), a single
package can be present for several reasons; without a trace, debugging a build
is guesswork.

---

## Questions the engine answers

- why is this **package** included?
- why is this **CONFIG** enabled?
- why is this **firmware** included?
- why is this **driver** included?
- why a **cache miss**?
- why a **package rebuild**?
- why was this **worker** selected?
- why is the **build blocked**?
- why is **release promotion denied**?

## Trace model

Each plan item carries one or more **trace entries**. A trace entry records:

```
item        : the thing being explained (package / CONFIG symbol / firmware / job / gate)
decision    : included | enabled | rebuilt | cache-miss | blocked | denied
source      : manual | profile | group | dependency | driver | security | layer
origin_ref  : the entity that caused it (profile id, group id, parent package,
              driver bundle, security rule, layer + priority)
detail      : human-readable explanation (e.g. which key field differed for a
              cache miss; which select pulled in a CONFIG; which layer overrode)
```

The **source** enumeration is fixed: `manual` (a wizard/profile override),
`profile`, `group` (package group/set), `dependency` (pulled in by another
package), `driver` (driver bundle), `security` (enforced by a security
profile), `layer` (contributed/overridden by a layer).

Examples:

- *why package `libnl` included?* → `source=dependency`, origin=`hostapd`,
  detail="runtime dependency of hostapd 2.10".
- *why `CONFIG_CFG80211=m`?* → `source=driver`, origin=`wifi-brcm` bundle,
  detail="selected by driver bundle; depends-on satisfied".
- *why cache miss for `busybox`?* → `source=manual`, detail="feature hash
  changed: applet set differs (added `ip`)".
- *why build blocked?* → `source=security`, origin=`hardened-default`,
  detail="security gate: root login enabled but profile forbids it".

## Where traces come from

Traces are emitted **during** `resolve.plan` (and the override/cache/security
sub-resolvers), not reconstructed afterwards. They are attached to the build
plan artifact and cached per build.

## Data model

`explain_traces(id, build_plan_id, item_kind, item_ref, decision, source,
origin_ref, detail, created_at)` — or computed-and-cached alongside the plan.

## API

`GET /v1/plan/explain` (for an unsaved plan request),
`GET /v1/builds/{id}/explain` (filterable by item kind / source).

## CLI

`osfabricumctl explain <item>` — e.g.
`osfabricumctl explain package:hostapd`,
`osfabricumctl explain config:CONFIG_CFG80211`,
`osfabricumctl explain cache-miss:busybox`,
`osfabricumctl explain blocked` (why the build is blocked).

## UI

Explain popovers throughout the Wizard review (step 24) and the build detail
page; each package/CONFIG/firmware/job row has a "why?" affordance. Integrates
with the Dependency Graph Viewer (M57): "what depends on this?" and "why
included?".

## Worker jobs

No dedicated job; the trace is a side output of `resolve.plan` and of the
override/security/cache resolvers.

## Artifacts

Explain trace attached to the build plan (`kind=build-plan` side data).

## Tests

- Each build-plan item has an explain trace.
- Trace records the correct **source**
  (manual/profile/group/dependency/driver/security/layer).
- A cache-miss explanation names the differing key field.
- An override explanation names the winning layer + priority.
- Explain is exposed in **both** UI and CLI.

## Acceptance criteria

All of the above. The Explain Engine is the user-facing proof that OSFabricum is
data-driven: every inclusion is traceable to data, never to a hidden code path.
