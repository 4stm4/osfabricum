"""Disk image composer (M17) — FAT16, MBR, boot files, raw image assembly."""

from osfabricum.image.composer import ImageComposeResult, ImageSpec, compose_image

__all__ = ["ImageComposeResult", "ImageSpec", "compose_image"]
