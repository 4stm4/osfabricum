"""Config rendering, overlay building, and first-boot task installation (M11).

Note: runtime settings (``load_settings``, ``Settings``) were moved to
``osfabricum.settings`` in M11 to avoid a naming conflict with this package.
"""

from osfabricum.config.firstboot import install_first_boot_tasks
from osfabricum.config.overlay import apply_overlay, build_overlay
from osfabricum.config.renderer import render_config, render_template_str

__all__ = [
    "apply_overlay",
    "build_overlay",
    "install_first_boot_tasks",
    "render_config",
    "render_template_str",
]
