"""GUI (server registry) に登録されている組み込みブロックが Python API からも
``flode.blocks`` 直下で import できることのガード。

2026-09-13 発見: ``Add`` (v0.35.0、Sum の矩形版) が registry には登録されている
一方 ``flode.blocks.__init__`` / ``__all__`` から抜けており、
``from flode.blocks import Add`` が ImportError だった。
"""

from __future__ import annotations

import importlib

import flode.blocks


def _registered_block_classes() -> list[tuple[str, str]]:
    from flode.server.registry import _BUILTIN_METADATA

    out: list[tuple[str, str]] = []
    for type_path in _BUILTIN_METADATA:
        module_path, cls_name = type_path.rsplit(".", 1)
        if module_path.startswith("flode.blocks."):
            out.append((module_path, cls_name))
    return out


def test_registry_covers_some_blocks() -> None:
    assert len(_registered_block_classes()) > 30


def test_every_registered_block_is_exported_from_flode_blocks() -> None:
    missing = []
    for module_path, cls_name in _registered_block_classes():
        cls = getattr(importlib.import_module(module_path), cls_name)
        if getattr(flode.blocks, cls_name, None) is not cls or cls_name not in flode.blocks.__all__:
            missing.append(f"{module_path}.{cls_name}")
    assert not missing, f"registered but not exported from flode.blocks: {missing}"


def test_add_is_importable_from_flode_blocks() -> None:
    from flode.blocks import Add

    assert Add(signs="+-").n_inputs == 2
