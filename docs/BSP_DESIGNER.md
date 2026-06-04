# Board/BSP Designer (M30)

The Board/BSP Designer provides a comprehensive system for managing Board Support Packages (BSP) in OSFabricum. It allows you to define and manage hardware-specific configurations including SoC families, board revisions, firmware blobs, device trees, flash methods, test methods, and probe profiles.

## Architecture

### Database Schema

The BSP system uses 10 new tables:

- `soc_families` - SoC family definitions (e.g., BCM2710, BCM2711)
- `board_revisions` - Hardware revisions of boards
- `board_firmware` - Firmware blobs required by boards
- `board_device_trees` - Device tree files (base and overlays)
- `board_default_kernels` - Default kernel configurations per board
- `board_default_toolchains` - Default toolchain configurations per board
- `board_supported_layouts` - Supported filesystem layouts
- `board_flash_methods` - Methods for flashing images to boards
- `board_test_methods` - Methods for testing board images
- `board_probe_profiles` - Auto-detection profiles for boards

Additionally, the `boot_schemes` table was extended with:
- `boot_type` - Type of boot process
- `requires_bootloader` - Whether a bootloader is required
- `requires_firmware` - Whether firmware blobs are required

## API Endpoints

### SoC Families

```bash
# List all SoC families
GET /v1/soc-families

# Create a new SoC family
POST /v1/soc-families
{
  "name": "BCM2711",
  "vendor": "Broadcom",
  "description": "ARM Cortex-A72 quad-core SoC",
  "metadata": {
    "cores": 4,
    "architecture": "ARM Cortex-A72"
  }
}
```

### Board Revisions

```bash
# List revisions for a board
GET /v1/boards/{board_id}/revisions

# Create a new board revision
POST /v1/boards/{board_id}/revisions
{
  "revision": "1.4",
  "soc_family_id": "uuid",
  "description": "Rev 1.4 with 8GB RAM",
  "is_default": true,
  "metadata": {
    "ram": "8GB"
  }
}
```

### Board BSP Data

```bash
# Get complete BSP data for a board
GET /v1/boards/{board_id}/bsp

# Add firmware blob
POST /v1/boards/{board_id}/firmware
{
  "filename": "start4.elf",
  "source_uri": "https://github.com/raspberrypi/firmware",
  "source_ref": "master",
  "required": true,
  "placement": "/boot"
}

# Add device tree
POST /v1/boards/{board_id}/device-trees
{
  "filename": "bcm2711-rpi-4-b.dtb",
  "dtb_type": "base",
  "required": true,
  "placement": "/boot"
}

# Add flash method
POST /v1/boards/{board_id}/flash-methods
{
  "method_name": "dd",
  "description": "Write image with dd",
  "command_template": "dd if={image} of={device} bs=4M",
  "requires_tools": ["dd"],
  "is_default": true
}

# Add test method
POST /v1/boards/{board_id}/test-methods
{
  "method_name": "qemu",
  "description": "Test with QEMU",
  "test_command": "qemu-system-aarch64 -M raspi4 -kernel {kernel}",
  "requires_tools": ["qemu-system-aarch64"],
  "timeout_seconds": 300,
  "is_default": true
}

# Add probe profile
POST /v1/boards/{board_id}/probe-profiles
{
  "probe_method": "device_tree",
  "match_pattern": "raspberrypi,4-model-b",
  "confidence": 100
}
```

All POST endpoints require authentication (see G-24).

## CLI Commands

### SoC Families

```bash
# List SoC families
osfabricumctl board soc-list

# Create SoC family
osfabricumctl board soc-create BCM2711 \
  --vendor Broadcom \
  --description "ARM Cortex-A72 SoC" \
  --metadata '{"cores": 4}'
```

### Board Revisions

```bash
# List board revisions
osfabricumctl board revision-list rpi4

# Create board revision
osfabricumctl board revision-create rpi4 "1.4" \
  --soc-family BCM2711 \
  --description "Rev 1.4 with 8GB RAM" \
  --default \
  --metadata '{"ram": "8GB"}'
```

### Board BSP

```bash
# Show complete BSP data
osfabricumctl board bsp-show rpi4

# Add firmware
osfabricumctl board firmware-add rpi4 start4.elf \
  --source-uri https://github.com/raspberrypi/firmware \
  --source-ref master \
  --placement /boot

# Add device tree
osfabricumctl board dtb-add rpi4 bcm2711-rpi-4-b.dtb base \
  --source-uri https://github.com/raspberrypi/linux \
  --placement /boot

# Add flash method
osfabricumctl board flash-add rpi4 dd \
  --description "Write with dd" \
  --command "dd if={image} of={device} bs=4M" \
  --tools dd \
  --default

# Add test method
osfabricumctl board test-add rpi4 qemu \
  --description "Test with QEMU" \
  --command "qemu-system-aarch64 -M raspi4 -kernel {kernel}" \
  --tools qemu-system-aarch64 \
  --timeout 300 \
  --default

# Add probe profile
osfabricumctl board probe-add rpi4 device_tree \
  --pattern "raspberrypi,4-model-b" \
  --confidence 100
```

### Seed Data

```bash
# Load BSP seed data from YAML files
osfabricumctl board seed --catalog-dir catalog/seed
```

## Seed Data Format

### SoC Families (`catalog/seed/soc_families.yaml`)

```yaml
apiVersion: osfabricum/v1
kind: SocFamilyList
items:
  - name: BCM2711
    vendor: Broadcom
    description: ARM Cortex-A72 quad-core SoC
    metadata:
      cores: 4
      architecture: ARM Cortex-A72
      frequency: 1.5 GHz
```

### Board Revisions (`catalog/seed/board_revisions.yaml`)

```yaml
apiVersion: osfabricum/v1
kind: BoardRevisionList
items:
  - board: rpi4
    revision: "1.4"
    soc_family: BCM2711
    description: Rev 1.4 with 8GB RAM
    is_default: true
    metadata:
      ram: 8GB
```

### Board BSP (`catalog/seed/board_bsp.yaml`)

```yaml
apiVersion: osfabricum/v1
kind: BoardBSPList

firmware:
  - board: rpi4
    filename: start4.elf
    source_uri: https://github.com/raspberrypi/firmware
    required: true
    placement: /boot

device_trees:
  - board: rpi4
    filename: bcm2711-rpi-4-b.dtb
    dtb_type: base
    required: true
    placement: /boot

flash_methods:
  - board: rpi4
    method_name: dd
    description: Write image with dd
    command_template: "dd if={image} of={device} bs=4M"
    requires_tools:
      - dd
    is_default: true

test_methods:
  - board: rpi4
    method_name: qemu
    description: Test with QEMU
    test_command: "qemu-system-aarch64 -M raspi4 -kernel {kernel}"
    requires_tools:
      - qemu-system-aarch64
    timeout_seconds: 300
    is_default: true

probe_profiles:
  - board: rpi4
    probe_method: device_tree
    match_pattern: raspberrypi,4-model-b
    confidence: 100
```

## Python API

```python
from osfabricum import board

# Create SoC family
soc = board.create_soc_family(
    name="BCM2711",
    vendor="Broadcom",
    description="ARM Cortex-A72 SoC",
    metadata={"cores": 4}
)

# Create board revision
rev = board.create_board_revision(
    board_id="rpi4",
    revision="1.4",
    soc_family_id=soc["id"],
    is_default=True
)

# Add firmware
firmware = board.add_board_firmware(
    board_id="rpi4",
    filename="start4.elf",
    source_uri="https://github.com/raspberrypi/firmware",
    required=True
)

# Get complete BSP data
bsp = board.get_board_with_bsp("rpi4")
print(f"Board: {bsp['name']}")
print(f"Revisions: {len(bsp['revisions'])}")
print(f"Firmware: {len(bsp['firmware'])}")
```

## Use Cases

### 1. Adding a New Board

```bash
# 1. Create SoC family (if needed)
osfabricumctl board soc-create "Rockchip RK3399" --vendor Rockchip

# 2. Create board revision
osfabricumctl board revision-create rock-pi-4 "1.4" \
  --soc-family "Rockchip RK3399" \
  --default

# 3. Add firmware blobs
osfabricumctl board firmware-add rock-pi-4 idbloader.img \
  --placement /boot

# 4. Add device tree
osfabricumctl board dtb-add rock-pi-4 rk3399-rock-pi-4b.dtb base \
  --placement /boot

# 5. Add flash method
osfabricumctl board flash-add rock-pi-4 dd \
  --command "dd if={image} of={device} bs=4M" \
  --default
```

### 2. Board Auto-Detection

Probe profiles enable automatic board detection:

```python
from osfabricum import board

# Get board BSP data
bsp = board.get_board_with_bsp("rpi4")

# Check probe profiles
for profile in bsp["probe_profiles"]:
    if profile["probe_method"] == "device_tree":
        # Check /proc/device-tree/compatible
        pattern = profile["match_pattern"]
        confidence = profile["confidence"]
```

### 3. Flashing Images

Flash methods provide standardized flashing procedures:

```python
bsp = board.get_board_with_bsp("rpi4")

# Get default flash method
default_method = next(
    m for m in bsp["flash_methods"] if m["is_default"]
)

# Execute flash command
command = default_method["command_template"].format(
    image="myimage.img",
    device="/dev/sdb"
)
# subprocess.run(command, shell=True)
```

## Testing

Run BSP tests:

```bash
# Run all BSP tests
pytest tests/unit/test_board_bsp.py tests/unit/test_board_seed.py -v

# Run specific test
pytest tests/unit/test_board_bsp.py::test_get_board_with_bsp -v
```

## Migration

The BSP schema is created by migration `77de5345d126_add_board_bsp_tables.py`. To apply:

```bash
alembic upgrade head
```

## Related Milestones

- **M25**: Universal OS Builder Model (base board table)
- **G-24**: Write API Authorization (protects BSP write endpoints)
- **M30**: Board/BSP Designer (this feature)

## Future Enhancements

- Web UI for BSP management
- Automatic firmware/DTB fetching
- Board compatibility matrix
- Hardware capability detection
- BSP versioning and rollback