"""QEMU boot harness (M22).

``build_qemu_command``
    Construct the ``qemu-system-*`` argv for a given :class:`QemuConfig`.
    Pure function — no side effects — so it is fully unit-testable.

``boot_capture``
    Boot the image under QEMU and capture the serial console transcript
    until a boot marker appears or the timeout elapses.  The actual
    subprocess launch is delegated to :func:`_spawn_qemu`, which is the
    single seam patched in tests.

Reproducibility / safety
------------------------
* QEMU runs headless (``-nographic``) with no network by default.
* The guest disk is attached read-only so a test run can never mutate the
  artifact image on disk.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Map OSFabricum arch → qemu-system binary + machine
_QEMU_ARCH: dict[str, tuple[str, str]] = {
    "aarch64": ("qemu-system-aarch64", "virt"),
    "arm": ("qemu-system-arm", "virt"),
    "x86_64": ("qemu-system-x86_64", "q35"),
    "x86": ("qemu-system-i386", "pc"),
    "riscv64": ("qemu-system-riscv64", "virt"),
}


@dataclass
class QemuConfig:
    """Configuration for a QEMU boot."""

    arch: str
    image_path: Path
    kernel_path: Path | None = None
    dtb_path: Path | None = None
    memory_mb: int = 256
    cpus: int = 1
    append: str = "console=ttyAMA0 root=/dev/vda2 rw"
    timeout_s: int = 60
    extra_args: list[str] = field(default_factory=list)

    def qemu_binary(self) -> str:
        bin_name, _ = _QEMU_ARCH.get(self.arch, ("qemu-system-x86_64", "q35"))
        return bin_name

    def machine(self) -> str:
        _, machine = _QEMU_ARCH.get(self.arch, ("qemu-system-x86_64", "q35"))
        return machine


def build_qemu_command(config: QemuConfig) -> list[str]:
    """Return the full ``qemu-system-*`` argv for *config*."""
    cmd: list[str] = [
        config.qemu_binary(),
        "-machine",
        config.machine(),
        "-m",
        str(config.memory_mb),
        "-smp",
        str(config.cpus),
        "-nographic",
        "-no-reboot",
        "-serial",
        "mon:stdio",
    ]

    # Attach the disk image read-only (safety: never mutate the artifact)
    cmd += [
        "-drive",
        f"file={config.image_path},format=raw,if=virtio,readonly=on",
    ]

    if config.kernel_path is not None:
        cmd += ["-kernel", str(config.kernel_path)]
        cmd += ["-append", config.append]
    if config.dtb_path is not None:
        cmd += ["-dtb", str(config.dtb_path)]

    cmd += config.extra_args
    return cmd


@dataclass
class BootResult:
    """Result of a QEMU boot capture."""

    booted: bool
    transcript: str
    timed_out: bool = False
    exit_code: int | None = None
    error: str | None = None


def _spawn_qemu(cmd: list[str], timeout_s: int) -> tuple[int | None, str, bool]:
    """Launch QEMU and capture stdout/stderr until exit or timeout.

    Returns ``(exit_code, transcript, timed_out)``.  This is the single
    function patched in unit tests so no real QEMU is required.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return proc.returncode, proc.stdout or "", False
    except subprocess.TimeoutExpired as exc:
        # On timeout QEMU is killed; partial output is still useful
        out = exc.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return None, out or "", True
    except FileNotFoundError:
        return None, "", False


def boot_capture(
    config: QemuConfig,
    boot_markers: list[str],
) -> BootResult:
    """Boot *config* under QEMU and capture the serial transcript.

    Parameters
    ----------
    config:
        The QEMU configuration.
    boot_markers:
        Strings whose presence in the transcript signals a successful boot.

    Returns
    -------
    BootResult
    """
    cmd = build_qemu_command(config)
    exit_code, transcript, timed_out = _spawn_qemu(cmd, config.timeout_s)

    if exit_code is None and not transcript and not timed_out:
        return BootResult(
            booted=False,
            transcript="",
            error=f"QEMU binary not found: {config.qemu_binary()!r}",
        )

    booted = any(m in transcript for m in boot_markers)
    return BootResult(
        booted=booted,
        transcript=transcript,
        timed_out=timed_out,
        exit_code=exit_code,
    )
