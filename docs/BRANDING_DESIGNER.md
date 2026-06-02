# OSFabricum — Branding / Identity Designer

**Milestone:** M39 (with M43 themes/fonts).
**Companion to:** [`ROADMAP.md`](ROADMAP.md) §18b.

Branding is a **first-class subsystem**, not "a wallpaper". A branding profile
targets many surfaces — from the bootloader splash to `/etc/os-release` to the
web UI — and produces real artifacts that the composer and image builder place
into the right partitions and paths.

> Treating branding as only a wallpaper is **forbidden** (anti-pattern #13).
> Desktop branding follows freedesktop conventions (`.desktop` entries, icon
> themes, `os-release`), so branding integrates with the Application Catalog
> (M41) and Theme Designer (M43), not a single image field.

---

## Data model

| Table | Purpose |
|-------|---------|
| `branding_profiles` | named identity, attachable to distribution/profile |
| `branding_assets` | logos, wallpapers, splash images, icons (as artifacts) |
| `branding_targets` | which surface each asset/template renders to |
| `theme_packages` | theme bundles (belong to the `branding`/`theme` layer) |
| `wallpaper_sets` | wallpaper collections |
| `boot_splash_themes` | plymouth/early-splash themes |
| `login_screen_themes` | greeter/login themes |
| `os_release_templates` | `/etc/os-release` templates |
| `motd_templates` | terminal MOTD templates |

## Branding targets

`bootloader`, `kernel cmdline splash`, `initramfs`, `plymouth`,
`login manager`, `desktop session`, `wallpaper`, `icon theme`,
`application menu`, `about dialog`, `web UI`, `terminal motd`,
`/etc/os-release`, `release manifest`, `installer`.

Each target is rendered independently — boot, login, and desktop branding can
differ. A branding profile that only sets `os-release` + `motd` is valid for a
headless server; a desktop profile additionally targets plymouth/login/desktop.

## API

`GET/POST /v1/branding-profiles`, `GET/PATCH /v1/branding-profiles/{id}`,
`POST /v1/branding-profiles/{id}/render`,
`POST /v1/branding-profiles/{id}/attach` (distribution|profile).

## CLI

`osfabricumctl branding create|show|edit|render|attach`,
`osfabricumctl branding asset add`.

## UI

`/branding`, `/branding/new`, `/branding/{id}`; surfaced in Wizard step 18.
Per-target preview (boot splash, login, desktop, os-release, motd).

## Worker jobs

`branding.render` (per target), feeding `rootfs.compose` / `image.compose`.

## Artifacts

Branding assets (`kind=branding-asset`); generated `/etc/os-release`; splash,
login, desktop assets; rendered MOTD; branding `.ofpkg` package (in the
`branding` layer).

## Tests

- Branding profile created; assets are artifacts.
- Attached to distribution/profile.
- `/etc/os-release` generated from template.
- Wallpaper/icon/theme selected.
- Boot/login/desktop branding **targeted separately**.
- Branding package belongs to the **branding layer** (taxonomy enforced).

## Acceptance criteria

All of the above. Branding output is explainable (M58) and contributes to the
release manifest and SBOM.
