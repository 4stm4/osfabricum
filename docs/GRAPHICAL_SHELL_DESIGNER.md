# OSFabricum — Graphical Shell Designer

**Milestone:** M40 (with M41 applications, M42 desktop integration, M43 themes).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

The graphical shell is a **resolved stack**, not a checkbox. A graphical profile
selects a coherent set of components (display server, compositor, display
manager, session, …) which **expand into a package set** for the chosen layer,
and which generate session/display-manager/autologin configuration.

> Treating the graphical shell as a single package checkbox is **forbidden**
> (anti-pattern #14). A "GNOME" choice is not one package; it expands to a
> compositor + display manager + session + settings/notification/power daemons +
> their dependencies, all attributed and explainable.

---

## Supported modes

`no-gui`, `kiosk`, `minimal-wayland`, `weston`, `labwc`, `sway`, `xfce`,
`lxqt`, `gnome`, `kde-plasma`, `custom-compositor`, `custom-launcher`.

A mode is a **preset** over the component fields below; the user can override
any field. `no-gui` expands to an empty graphical package set (and hides Wizard
steps 16–18 unless overridden).

## Component fields

display server · compositor · display manager · greeter · session · autologin ·
kiosk app · panel/launcher · notification daemon · settings daemon · power
manager · file manager · terminal · input method · screen lock · accessibility.

## Data model

| Table | Purpose |
|-------|---------|
| `graphical_profiles` | named GUI stack, attachable to a profile |
| `graphical_profile_components` | profile → component selections |
| `graphical_sessions` | generated session definitions |

Component selections reference **applications** (M41) and **packages** (M35),
so the file manager / terminal / browser are real catalog entries, not strings.

## Expansion → package set

`POST /v1/graphical-profiles/{id}/expand` runs `graphical.expand`: it resolves
the selected components into a `package_set` in the `desktop`/`runtime` layers,
pulling dependencies. The expansion is **explainable** — each package's
inclusion is attributed to the component that required it (M58).

## Config generation

`graphical.render` generates:
- display-manager config (autologin, default session),
- session files (`.desktop` session, Wayland/X startup),
- kiosk launcher (single-app autostart) when mode = `kiosk`.

## API

`GET/POST /v1/graphical-profiles`, `GET/PATCH /v1/graphical-profiles/{id}`,
`POST /v1/graphical-profiles/{id}/expand`,
`POST /v1/graphical-profiles/{id}/render`,
`POST /v1/graphical-profiles/{id}/attach`.

## CLI

`osfabricumctl graphical create|show|edit|expand|render|attach`.

## UI

`/graphical`, `/graphical/new`, `/graphical/{id}`; Wizard step 16. Shows the
expanded package set and the generated session/DM config.

## Worker jobs

`graphical.expand` (→ package set), `graphical.render` (→ config artifacts).

## Artifacts

Expanded package set; session files; display-manager config; autologin config;
kiosk launcher.

## Tests

- Graphical profile attached to a profile.
- GUI stack **expands** to desktop/runtime packages (mode → package set).
- Session files generated.
- Autologin configurable.
- **Kiosk mode launches one app.**
- Display-manager config generated.

## Acceptance criteria

All of the above. The graphical profile composes with branding (M39), themes
(M43), applications (M41), and desktop integration (M42) — each a distinct
subsystem, none collapsed into a checkbox.
