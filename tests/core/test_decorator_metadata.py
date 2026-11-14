"""``@block`` のメタデータ引数のテスト (ADR-0081 §論点 7-A / SPEC-0033)。

``category`` / ``display_name`` / ``description`` / ``choices`` / ``param_descriptions``
を生成クラスの公開 class 属性 ``block_*`` として載せること、宣言の検証、class 形での
``block_*`` 名の予約、メタデータ付きブロックの保存 → 読み込みの往復を確かめる。
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

import pytest

from flode import Simulator, block
from flode.core.block_metadata import METADATA_ATTRIBUTES
from flode.core.persistence import register_block_module, reset_block_module_allowlist
from flode.exceptions import BlockSpecError


def _function_form(**deco: Any) -> type:
    @block(**deco)
    def shaped(t: float, u: float, *, mode: str = "fast", k: float = 1.0) -> float:
        return k * u

    return shaped


def _class_form(**deco: Any) -> type:
    @block(**deco)
    class Shaped:
        mode: str = "fast"
        k: float = 1.0

        def output(self, t: float, u: float) -> float:
            return self.k * u

    return Shaped


_FORMS = pytest.mark.parametrize("make", [_function_form, _class_form], ids=["function", "class"])


# ---------------------------------------------------------------------------
# 公開 class 属性
# ---------------------------------------------------------------------------


class TestMetadataAttributes:
    @_FORMS
    def test_all_arguments_become_public_class_attributes(self, make) -> None:
        cls = make(
            category="Filters",
            display_name="Shaped gain",
            description="Multiplies the input.",
            choices={"mode": ["fast", "slow"]},
            param_descriptions={"k": "Gain factor", "mode": "Speed"},
        )
        assert cls.block_category == "Filters"
        assert cls.block_display_name == "Shaped gain"
        assert cls.block_description == "Multiplies the input."
        assert cls.block_choices == {"mode": ("fast", "slow")}
        assert cls.block_param_descriptions == {"k": "Gain factor", "mode": "Speed"}
        # 表示名・説明はそのクラス自身の __dict__ に載る (派生が基底の表示名を名乗らない規則の前提)
        assert "block_display_name" in vars(cls)
        assert "block_description" in vars(cls)

    @_FORMS
    def test_omitted_arguments_are_not_written(self, make) -> None:
        cls = make()
        for attr in (*METADATA_ATTRIBUTES, "block_hidden"):
            assert attr not in vars(cls), attr

    @_FORMS
    def test_mapping_display_name_and_description(self, make) -> None:
        cls = make(
            display_name={"ja": "整形ゲイン", "en": "Shaped gain"},
            description={"ja": "入力を k 倍する", "en": "Multiplies the input."},
        )
        assert cls.block_display_name == {"ja": "整形ゲイン", "en": "Shaped gain"}
        assert cls.block_description == {"ja": "入力を k 倍する", "en": "Multiplies the input."}

    @_FORMS
    def test_port_names_are_published(self, make) -> None:
        cls = make(input_names=("in",), output_names=("out",))
        assert cls.block_input_names == ("in",)
        assert cls.block_output_names == ("out",)

    @_FORMS
    def test_only_given_arguments_are_written(self, make) -> None:
        cls = make(category="Filters")
        assert cls.block_category == "Filters"
        assert "block_choices" not in vars(cls)

    def test_metadata_does_not_change_structure_or_behaviour(self) -> None:
        plain = _function_form()
        rich = _function_form(category="Filters", choices={"mode": ["fast", "slow"]})
        assert plain._flode_structure == rich._flode_structure
        assert plain._flode_params_spec == rich._flode_params_spec

    def test_instances_see_class_metadata(self) -> None:
        cls = _class_form(category="Filters")
        assert cls(id="b").block_category == "Filters"

    def test_choices_value_is_not_enforced_at_instantiation(self) -> None:
        """``choices`` は Inspector の選択肢の宣言で、Python API からの値は制限しない。"""
        cls = _function_form(choices={"mode": ["fast", "slow"]})
        assert cls(id="b", mode="other")._params["mode"] == "other"


# ---------------------------------------------------------------------------
# 検証
# ---------------------------------------------------------------------------


class TestMetadataValidation:
    @pytest.mark.parametrize("bad", ["", "   ", 3, ["Filters"]])
    def test_category_must_be_non_empty_str(self, bad) -> None:
        with pytest.raises(BlockSpecError, match="category"):
            _function_form(category=bad)

    @pytest.mark.parametrize("field", ["display_name", "description"])
    @pytest.mark.parametrize("bad", [3, {}, {"ja": 1}, {1: "x"}, ["a"]])
    def test_text_fields_must_be_str_or_str_mapping(self, field, bad) -> None:
        with pytest.raises(BlockSpecError, match=field):
            _function_form(**{field: bad})

    @_FORMS
    def test_choices_key_must_be_a_parameter(self, make) -> None:
        with pytest.raises(BlockSpecError, match="'speed'"):
            make(choices={"speed": ["fast"]})

    @_FORMS
    def test_default_must_be_among_choices(self, make) -> None:
        with pytest.raises(BlockSpecError, match="default"):
            make(choices={"mode": ["slow", "medium"]})

    @pytest.mark.parametrize(
        "bad",
        [
            {"mode": []},  # 空
            {"mode": "fast"},  # 文字列そのもの (列ではない)
            {"mode": ["fast", 2]},  # 非文字列の候補
            {"mode": ["fast", "fast"]},  # 重複
            ["mode"],  # Mapping ではない
        ],
    )
    def test_choices_values_must_be_non_empty_unique_str_sequences(self, bad) -> None:
        with pytest.raises(BlockSpecError, match="choices"):
            _function_form(choices=bad)

    def test_choices_on_required_parameter_skips_default_check(self) -> None:
        @block(choices={"mode": ["a", "b"]})
        def needs_mode(t: float, u: float, *, mode: str) -> float:
            return u

        assert needs_mode.block_choices == {"mode": ("a", "b")}

    @_FORMS
    def test_param_descriptions_key_must_be_a_parameter(self, make) -> None:
        with pytest.raises(BlockSpecError, match="'gain'"):
            make(param_descriptions={"gain": "x"})

    @pytest.mark.parametrize("bad", [{"k": 1}, ["k"], {"k": {"ja": ""}}, {"k": {}}])
    def test_param_descriptions_values_must_be_str_or_language_map(self, bad) -> None:
        with pytest.raises(BlockSpecError, match="param_descriptions"):
            _function_form(param_descriptions=bad)

    def test_param_descriptions_accept_language_map(self) -> None:
        cls = _function_form(param_descriptions={"k": {"ja": "ゲイン", "en": "Gain"}})
        assert cls.block_param_descriptions == {"k": {"ja": "ゲイン", "en": "Gain"}}

    def test_choices_are_copied_not_aliased(self) -> None:
        options = ["fast", "slow"]
        decl = {"mode": options}
        cls = _function_form(choices=decl)
        options.append("late")
        decl["k"] = ["x"]
        assert cls.block_choices == {"mode": ("fast", "slow")}


class TestClassFormReservedNames:
    @pytest.mark.parametrize("attr", sorted(METADATA_ATTRIBUTES))
    def test_metadata_field_is_rejected(self, attr: str) -> None:
        namespace = {
            "__annotations__": {attr: str},
            attr: "x",
            "output": lambda self, t, u: u,
        }
        user_cls = type("Bad", (), namespace)
        user_cls.output.__annotations__ = {"t": float, "u": float, "return": float}
        with pytest.raises(BlockSpecError, match=attr):
            block(user_cls)

    def test_required_metadata_field_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="block_category"):

            @block
            class Bad:
                block_category: str

                def output(self, t: float, u: float) -> float:
                    return u

    def test_other_block_prefixed_field_is_allowed(self) -> None:
        """予約はメタデータ属性と同名のものだけ (``block_size`` 等は従来どおり使える)。"""

        @block
        class Chunked:
            block_size: int = 4

            def output(self, t: float, u: float) -> float:
                return u * self.block_size

        inst = Chunked(id="b", block_size=8)
        assert inst.block_size == 8
        assert inst._params == {"block_size": 8}

    def test_hidden_marker_is_copied_to_generated_class(self) -> None:
        @block
        class Base:
            block_hidden = True

            def output(self, t: float, u: float) -> float:
                return u

        assert vars(Base)["block_hidden"] is True
        assert Base._flode_params_spec == ()

    def test_without_hidden_marker_no_attribute(self) -> None:
        assert "block_hidden" not in vars(_class_form())

    def test_annotated_hidden_marker_is_rejected(self) -> None:
        """注釈を付けるとパラメータ (フィールド) になってしまうため拒否する。"""
        with pytest.raises(BlockSpecError, match="block_hidden"):

            @block
            class Bad:
                block_hidden: bool = True

                def output(self, t: float, u: float) -> float:
                    return u

    def test_non_bool_hidden_marker_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="block_hidden must be a bool"):

            @block
            class Bad:
                block_hidden = "yes"

                def output(self, t: float, u: float) -> float:
                    return u

    def test_metadata_plain_attribute_is_rejected(self) -> None:
        """注釈なしでもメタデータ属性と同名なら、取り違えないよう拒否する。"""
        with pytest.raises(BlockSpecError, match="block_display_name"):

            @block
            class Bad:
                block_display_name = "x"

                def output(self, t: float, u: float) -> float:
                    return u

    def test_function_form_keyword_named_block_is_allowed(self) -> None:
        """関数形の引数はインスタンス属性にならないので予約の対象外。"""

        @block
        def ok(t: float, u: float, *, block_size: int = 4) -> float:
            return u

        assert ok(id="b")._params == {"block_size": 4}


# ---------------------------------------------------------------------------
# 保存 → 読み込み
# ---------------------------------------------------------------------------

_METADATA_BLOCKS_SOURCE = """\
from flode import block


@block(
    category="Filters",
    display_name={"ja": "整形", "en": "Shaper"},
    description="Shapes the input.",
    choices={"mode": ["fast", "slow"]},
    param_descriptions={"k": "Gain"},
    port_shapes_in=((2,),),
    port_shapes_out=((2,),),
)
def shaper(t: float, u: float, *, mode: str = "fast", k: float = 2.0) -> float:
    return k * u


@block(category="Sinks", display_name="Logger")
def logger_sink(t: float, u: float, *, tag: str = "a") -> None:
    pass


@block(category="Filters", choices={"mode": ["a", "b"]})
class picker:
    mode: str = "a"

    def output(self, t: float, u: float) -> float:
        return u
"""


@pytest.fixture
def metadata_blocks_module(tmp_path, monkeypatch):
    """メタデータ付き ``@block`` を持つ import 可能なモジュール (``metablocks_probe.blocks``)。"""
    package = tmp_path / "metablocks_probe"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "blocks.py").write_text(_METADATA_BLOCKS_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    register_block_module("metablocks_probe.")
    try:
        yield importlib.import_module("metablocks_probe.blocks")
    finally:
        reset_block_module_allowlist()
        for name in [m for m in sys.modules if m.split(".")[0] == "metablocks_probe"]:
            del sys.modules[name]


class TestMetadataRoundTrip:
    @pytest.mark.parametrize(
        ("attr", "params"),
        [
            ("shaper", {"mode": "slow", "k": 3.0}),
            ("logger_sink", {"tag": "z"}),
            ("picker", {"mode": "b"}),
        ],
    )
    def test_save_and_load(self, metadata_blocks_module, tmp_path, attr, params) -> None:
        cls = getattr(metadata_blocks_module, attr)
        sim = Simulator(t_end=0.02, dt=0.01)
        sim.add(cls(id="b", **params))
        path = tmp_path / "model.flw.json"
        sim.save(path)
        entry = json.loads(path.read_text(encoding="utf-8"))["blocks"][0]
        # メタデータはクラスの宣言で、モデルには書かない
        assert set(entry) <= {"id", "type", "params"}
        assert entry["params"] == params
        loaded = Simulator.load(path).get_block("b")
        assert type(loaded) is cls
        assert loaded._params == params
        assert loaded.block_category == cls.block_category

    def test_loaded_sink_model_runs(self, metadata_blocks_module, tmp_path) -> None:
        from flode.blocks import Ramp

        sim = Simulator(t_end=0.02, dt=0.01)
        sim.add(Ramp(slope=1.0, id="r"))
        sim.add(metadata_blocks_module.logger_sink(id="s"))
        sim.connect("r", "s")
        path = tmp_path / "model.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        loaded.run()
        assert loaded.get_block("s").n_outputs == 0
