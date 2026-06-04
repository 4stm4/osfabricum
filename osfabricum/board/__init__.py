"""Board/BSP management (M30)."""

from osfabricum.board.service import (
    add_board_device_tree,
    add_board_firmware,
    add_board_flash_method,
    add_board_probe_profile,
    add_board_test_method,
    create_board_revision,
    create_soc_family,
    get_board_with_bsp,
    list_board_revisions,
    list_soc_families,
)

__all__ = [
    "create_soc_family",
    "list_soc_families",
    "create_board_revision",
    "list_board_revisions",
    "get_board_with_bsp",
    "add_board_firmware",
    "add_board_device_tree",
    "add_board_flash_method",
    "add_board_test_method",
    "add_board_probe_profile",
]

# Made with Bob
