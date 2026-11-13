"""``flode.server.block_catalog`` の単体テスト (registry の合成・保護対象のルート・メタデータ)。"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from flode.server.block_catalog import (
    compose_catalog,
    reload_allowed,
    user_block_roots,
)
from flode.server.registry import BlockMetadata, build_user_block_metadata
from flode.server.settings import Settings
from flode.userblocks import (
    BlockLoadReport,
    LoadRequest,
    SourceInfo,
    UserBlockInfo,
    UserParamSpec,
)


def _info(type_path: str, **overrides: Any) -> UserBlockInfo:
    info = UserBlockInfo(
        type_path=type_path,
        class_name=type_path.rsplit(".", 1)[1],
        source="module:mypkg",
        module=type_path.rsplit(".", 1)[0],
        path=None,
        display_name="Probe",
        display_name_i18n={},
        description="",
        description_i18n={},
        docstring="",
        category=None,
        params=(UserParamSpec(name="k", type="float", default=1.0),),
        n_inputs=0,
        n_outputs=1,
        n_states=1,
        direct_feedthrough=False,
        port_shapes_in=(),
        port_shapes_out=((3,),),
        input_names=(),
        output_names=(),
        block_class=object,
    )
    return dataclasses.replace(info, **overrides)


def _builtin(type_path: str) -> BlockMetadata:
    return BlockMetadata(
        type_path=type_path,
        display_name="X",
        category="sources",
        icon="x",
        docstring_summary="",
        docstring_full="",
        params_spec=[],
        default_n_inputs=0,
        default_n_outputs=1,
        port_shapes_in_default=[],
        port_shapes_out_default=[[]],
    )


class TestComposeCatalog:
    def test_user_blocks_follow_builtin_and_replace_duplicates(self, tmp_path: Path) -> None:
        builtin = [_builtin("flode.blocks.sources.Constant"), _builtin("mypkg.Probe")]
        report = BlockLoadReport(blocks=("mypkg.Probe",), block_infos=(_info("mypkg.Probe"),))

        catalog = compose_catalog(builtin, report, Settings(workspace_root=tmp_path))

        assert [m.type_path for m in catalog.blocks] == [
            "flode.blocks.sources.Constant",
            "mypkg.Probe",
        ]
        assert catalog.blocks[-1].source == "module:mypkg"
        assert catalog.builtin == tuple(builtin)

    def test_without_report_is_builtin_only(self, tmp_path: Path) -> None:
        builtin = [_builtin("flode.blocks.sources.Constant")]
        catalog = compose_catalog(builtin, None, Settings(workspace_root=tmp_path))
        assert catalog.blocks == tuple(builtin)
        assert catalog.report is None
        # ユーザーブロックを読まない設定でもワークスペースの blocks/ は守る
        assert catalog.protected_roots == (tmp_path / "blocks",)


class _DiscreteProbe:
    requires_discrete_rate = True


class TestUserBlockMetadata:
    def test_defaults(self) -> None:
        meta = build_user_block_metadata(_info("mypkg.Probe"))
        assert meta.tags == ["sm_b", "stateful", "source"]
        assert meta.category == ""
        assert meta.icon == "default"
        assert meta.is_container is False
        assert meta.mask_capable is False
        assert meta.requires_discrete_rate is False
        assert meta.port_shapes_out_default == [[3]]
        assert [(p.name, p.has_default, p.enum_values) for p in meta.params_spec] == [
            ("k", True, None)
        ]

    def test_scalar_sink_with_choices_and_descriptions(self) -> None:
        info = _info(
            "mypkg.Sink",
            n_inputs=2,
            n_outputs=0,
            n_states=0,
            port_shapes_in=((), ()),
            port_shapes_out=(),
            category="IO",
            description="Write it.",
            description_i18n={"ja": "書く", "en": "Write it."},
            display_name_i18n={"ja": "書き出し", "en": "Writer"},
            docstring="Write it.\n\nMore.",
            input_names=("a", "b"),
            params=(
                UserParamSpec(
                    name="mode", type="str", default="csv", description="Format", choices=("csv",)
                ),
            ),
        )
        meta = build_user_block_metadata(info)
        assert meta.tags == ["sm_a", "sink"]
        assert meta.category == "IO"
        assert meta.docstring_summary == "Write it."
        assert meta.docstring_summary_i18n == {"ja": "書く", "en": "Write it."}
        assert meta.display_name_i18n == {"ja": "書き出し", "en": "Writer"}
        assert meta.docstring_full == "Write it.\n\nMore."
        assert meta.input_names == ["a", "b"]
        assert meta.output_names == []
        assert [(p.name, p.description, p.enum_values) for p in meta.params_spec] == [
            ("mode", "Format", ["csv"])
        ]

    def test_requires_discrete_rate_is_read_statically(self) -> None:
        meta = build_user_block_metadata(_info("mypkg.D", block_class=_DiscreteProbe))
        assert meta.requires_discrete_rate is True

    def test_truthy_non_bool_is_not_discrete(self) -> None:
        class Odd:
            requires_discrete_rate = "yes"

        assert (
            build_user_block_metadata(_info("mypkg.D", block_class=Odd)).requires_discrete_rate
            is False
        )


class TestUserBlockRoots:
    def test_collects_request_and_report_roots(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        lab = tmp_path / "lab"
        request = LoadRequest(workspace=ws, dirs=(("lab", lab),))
        report = BlockLoadReport(
            sources=(
                SourceInfo(
                    id="workspace",
                    kind="workspace",
                    label="blocks/",
                    root=str(ws / "blocks"),
                    reloadable=True,
                ),
            )
        )
        roots = user_block_roots(Settings(workspace_root=ws, user_blocks_request=request), report)
        assert roots == (ws / "blocks", lab)

    def test_unknown_module_adds_nothing(self, tmp_path: Path) -> None:
        request = LoadRequest(modules=("no_such_module_probe_xyz.blocks",))
        roots = user_block_roots(
            Settings(workspace_root=tmp_path, user_blocks_request=request), None
        )
        assert roots == (tmp_path / "blocks",)


@pytest.mark.parametrize(
    ("enabled", "allowed", "loopback", "expected"),
    [
        (True, True, True, True),
        (False, True, True, False),
        (True, False, True, False),
        (True, True, False, False),
    ],
)
def test_reload_allowed_requires_all_three(
    tmp_path: Path, enabled: bool, allowed: bool, loopback: bool, expected: bool
) -> None:
    settings = Settings(
        workspace_root=tmp_path,
        user_blocks_enabled=enabled,
        user_blocks_reload_allowed=allowed,
        loopback_bind=loopback,
    )
    assert reload_allowed(settings) is expected
