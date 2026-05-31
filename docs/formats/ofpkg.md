# .ofpkg Package Format — v1

An `.ofpkg` file is a **ZIP archive** (no compression at the outer level) that
bundles a binary package and its metadata for distribution and installation on
OSFabricum-managed systems.

---

## Archive structure

```
<name>-<version>-<arch>.ofpkg   (ZIP, store compression)
├── manifest.json               required — package metadata
├── files.tar.gz                required — installed files (gzip-compressed tar)
├── checksums.sha256            required — SHA-256 of all other members
└── sbom.json                   required — CycloneDX 1.4 SBOM
```

All four members must be present. Additional members are ignored by the
installer but preserved by tools.

---

## manifest.json

UTF-8 JSON object.  Required fields are marked **bold**.

| Field | Type | Description |
|---|---|---|
| **`format_version`** | string | Must be `"1"` |
| **`name`** | string | Package name, e.g. `"nanodhcp"` |
| **`version`** | string | Version string, e.g. `"1.0.0"` |
| **`arch`** | string | Target architecture, e.g. `"aarch64"` |
| `description` | string | Human-readable description |
| `license` | string | SPDX expression, e.g. `"MIT"` |
| `dependencies` | array | Runtime/build dependency list (see below) |
| `build_system` | string | Build system used (from M8 driver names) |
| `source_hash` | string | SHA-256 of the upstream source artifact |
| `recipe_hash` | string | SHA-256 of the build recipe specification |

### dependencies entry

```json
{ "name": "libc", "type": "run", "constraint": ">=2.36" }
```

`type` is one of `run`, `build`, `test`.  `constraint` is optional.

### Example

```json
{
  "format_version": "1",
  "name": "nanodhcp",
  "version": "1.0.0",
  "arch": "aarch64",
  "description": "Minimal DHCP client for embedded Linux",
  "license": "MIT",
  "dependencies": [],
  "build_system": "make",
  "source_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "recipe_hash":  "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3"
}
```

---

## files.tar.gz

A **gzip-compressed tar** archive of the package's installed files.  Paths are
stored **relative to the installation prefix** (strip the leading `/`):

```
usr/bin/nanodhcp
usr/share/man/man8/nanodhcp.8.gz
```

The installer extracts this archive into the target prefix with the same
relative paths.

---

## checksums.sha256

A plain-text file with one entry per line:

```
<sha256-hex>  manifest.json
<sha256-hex>  files.tar.gz
<sha256-hex>  sbom.json
```

The `checksums.sha256` file itself is **not** listed (it cannot hash itself).
The installer rejects the package if any digest does not match.

---

## sbom.json

A minimal **CycloneDX 1.4** SBOM in JSON format.  Required top-level fields:

| Field | Value |
|---|---|
| `bomFormat` | `"CycloneDX"` |
| `specVersion` | `"1.4"` |
| `version` | integer (increment each rebuild) |
| `components` | array of component objects |

### Minimum component object

```json
{
  "type": "library",
  "name": "nanodhcp",
  "version": "1.0.0",
  "purl": "pkg:generic/nanodhcp@1.0.0"
}
```

---

## Tamper detection

1. The installer opens the ZIP and reads `checksums.sha256`.
2. Each listed file is read and its SHA-256 is computed.
3. If any digest mismatches the stored value the installation is **aborted**
   before any files are written to disk.
4. `manifest.json` schema is validated after checksum verification.
5. `sbom.json` CycloneDX fields are validated after checksum verification.

---

## MIME type / file extension

| Attribute | Value |
|---|---|
| File extension | `.ofpkg` |
| MIME type | `application/x-ofpkg` |
| Magic bytes | `PK\x03\x04` (standard ZIP) |
