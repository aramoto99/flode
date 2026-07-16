"""Built-in ``std.flwlib.json`` ジェネレータ (ADR-0029)。

PID コントローラ・1 次遅れプラント・2 次プラントの 3 entry をハンドコーディングした
Subsystem ``params`` dict から :meth:`Subsystem._from_dict` で組み立て直し、
:meth:`Subsystem.to_dict` で再シリアライズしてから ``.flwlib.json`` ファイルに書き出す。

これにより ``flode/libraries/std.flwlib.json`` の subsystem body は
``Subsystem.to_dict()`` の出力と byte-identical となり、frontend 側で Inline 配置
した後に ``Simulator.load`` で再構築する経路が丸ごと round-trip 安全になる。

実行方法 (リポジトリルートから):

    python tools/build_std_library.py

ファイルが既に存在しても上書きする (= バージョン管理にコミットすべきソース)。

.. note::

   1 次プラント・2 次プラントは ADR-0021 §(7) Phase 3 制約 (placeholder は scalar
   完全一致のみ) に従い、各係数を **個別 mask param** で持たせる簡易版を採用する。
   Phase 5+ で式 placeholder が入ったら ``omega_n`` / ``zeta`` パラメトリゼーションに
   切り替える。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flode import Subsystem
from flode.libraries import CURRENT_LIBRARY_SCHEMA_VERSION


def _build_subsystem(params: dict[str, Any]) -> dict[str, Any]:
    """``params`` から ``Subsystem`` を組み立て、``.to_dict()`` 結果を返す。

    placeholder ``"$Kp"`` 等は :meth:`Subsystem._from_dict` 経由で
    ``_unresolved_params`` として保存され、``to_dict`` で再びシリアライズされる
    (= byte-identical round-trip)。

    .. note::

        各内部 block の ``params`` を ``{}`` でハンドコードしてあっても、
        ``Block.__init__`` の default 値 (例: ``Integrator(x0=0.0)``) が
        ``self._params = {"x0": ...}`` で記録される。そのため round-trip 後の
        ``to_dict()`` 出力には ``x0`` 等の補完されたフィールドが現れる
        (= ``std.flwlib.json`` で見える)。これは byte-identical 保証の対象内。
    """
    sub = Subsystem._from_dict(**params)
    return sub.to_dict()


def build_pid_params() -> dict[str, Any]:
    """PID コントローラの subsystem params (= Subsystem.to_dict 形式)。

    1 入力 (error) → 1 出力 (control)、内部 P/I/D 並列。
    """
    return {
        "n_inputs": 1,
        "n_outputs": 1,
        "mask_params": [
            {
                "name": "Kp",
                "type": "float",
                "default": 1.0,
                "description": "Proportional gain",
            },
            {
                "name": "Ki",
                "type": "float",
                "default": 0.1,
                "description": "Integral gain",
            },
            {
                "name": "Kd",
                "type": "float",
                "default": 0.0,
                "description": "Derivative gain",
            },
        ],
        "mask_values": {"Kp": 1.0, "Ki": 0.1, "Kd": 0.0},
        "blocks": [
            {
                "id": "Inport_0",
                "type": "flode.subsystems.ports.Inport",
                "params": {"port_idx": 0},
            },
            {
                "id": "Gain_P",
                "type": "flode.blocks.mathops.Gain",
                "params": {"k": "$Kp"},
            },
            {
                "id": "Integrator_0",
                "type": "flode.blocks.continuous.Integrator",
                "params": {},
            },
            {
                "id": "Gain_I",
                "type": "flode.blocks.mathops.Gain",
                "params": {"k": "$Ki"},
            },
            {
                "id": "Derivative_0",
                "type": "flode.blocks.continuous.Derivative",
                "params": {},
            },
            {
                "id": "Gain_D",
                "type": "flode.blocks.mathops.Gain",
                "params": {"k": "$Kd"},
            },
            {
                "id": "Sum_0",
                "type": "flode.blocks.mathops.Sum",
                "params": {"signs": "+++"},
            },
            {
                "id": "Outport_0",
                "type": "flode.subsystems.ports.Outport",
                "params": {"port_idx": 0},
            },
        ],
        "connections": [
            {"src": "Inport_0", "src_idx": 0, "dst": "Gain_P", "dst_idx": 0},
            {"src": "Inport_0", "src_idx": 0, "dst": "Integrator_0", "dst_idx": 0},
            {"src": "Integrator_0", "src_idx": 0, "dst": "Gain_I", "dst_idx": 0},
            {"src": "Inport_0", "src_idx": 0, "dst": "Derivative_0", "dst_idx": 0},
            {"src": "Derivative_0", "src_idx": 0, "dst": "Gain_D", "dst_idx": 0},
            {"src": "Gain_P", "src_idx": 0, "dst": "Sum_0", "dst_idx": 0},
            {"src": "Gain_I", "src_idx": 0, "dst": "Sum_0", "dst_idx": 1},
            {"src": "Gain_D", "src_idx": 0, "dst": "Sum_0", "dst_idx": 2},
            {"src": "Sum_0", "src_idx": 0, "dst": "Outport_0", "dst_idx": 0},
        ],
    }


def build_first_order_plant_params() -> dict[str, Any]:
    """1 次遅れプラント ``G(s) = K / (tau*s + 1)`` の subsystem params。"""
    return {
        "n_inputs": 1,
        "n_outputs": 1,
        "mask_params": [
            {
                "name": "K",
                "type": "float",
                "default": 1.0,
                "description": "DC gain",
            },
            {
                "name": "tau",
                "type": "float",
                "default": 1.0,
                "description": "Time constant (s)",
            },
        ],
        "mask_values": {"K": 1.0, "tau": 1.0},
        "blocks": [
            {
                "id": "Inport_0",
                "type": "flode.subsystems.ports.Inport",
                "params": {"port_idx": 0},
            },
            {
                "id": "TransferFunction_0",
                "type": "flode.blocks.continuous.TransferFunction",
                "params": {
                    "numerator": ["$K"],
                    "denominator": ["$tau", 1.0],
                },
            },
            {
                "id": "Outport_0",
                "type": "flode.subsystems.ports.Outport",
                "params": {"port_idx": 0},
            },
        ],
        "connections": [
            {
                "src": "Inport_0",
                "src_idx": 0,
                "dst": "TransferFunction_0",
                "dst_idx": 0,
            },
            {
                "src": "TransferFunction_0",
                "src_idx": 0,
                "dst": "Outport_0",
                "dst_idx": 0,
            },
        ],
    }


def build_second_order_plant_params() -> dict[str, Any]:
    """2 次プラント ``G(s) = K / (a*s^2 + b*s + 1)`` の subsystem params (簡易版)。"""
    return {
        "n_inputs": 1,
        "n_outputs": 1,
        "mask_params": [
            {
                "name": "K",
                "type": "float",
                "default": 1.0,
                "description": "DC gain",
            },
            {
                "name": "a",
                "type": "float",
                "default": 1.0,
                "description": "s^2 coefficient (= 1/omega_n^2)",
            },
            {
                "name": "b",
                "type": "float",
                "default": 1.0,
                "description": "s coefficient (= 2*zeta/omega_n)",
            },
        ],
        "mask_values": {"K": 1.0, "a": 1.0, "b": 1.0},
        "blocks": [
            {
                "id": "Inport_0",
                "type": "flode.subsystems.ports.Inport",
                "params": {"port_idx": 0},
            },
            {
                "id": "TransferFunction_0",
                "type": "flode.blocks.continuous.TransferFunction",
                "params": {
                    "numerator": ["$K"],
                    "denominator": ["$a", "$b", 1.0],
                },
            },
            {
                "id": "Outport_0",
                "type": "flode.subsystems.ports.Outport",
                "params": {"port_idx": 0},
            },
        ],
        "connections": [
            {
                "src": "Inport_0",
                "src_idx": 0,
                "dst": "TransferFunction_0",
                "dst_idx": 0,
            },
            {
                "src": "TransferFunction_0",
                "src_idx": 0,
                "dst": "Outport_0",
                "dst_idx": 0,
            },
        ],
    }


def main() -> None:
    repo_root = Path(__file__).parent.parent
    out_path = repo_root / "flode" / "libraries" / "std.flwlib.json"

    pid_dict = _build_subsystem(build_pid_params())
    fop_dict = _build_subsystem(build_first_order_plant_params())
    sop_dict = _build_subsystem(build_second_order_plant_params())

    library = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": "std",
        "display_name": "Standard Library",
        "description": "Built-in mask Subsystem templates shipped with flode.",
        "version": "0.13.0",
        "display_name_i18n": {
            "en": "Standard Library",
            "ja": "標準ライブラリ",
        },
        "description_i18n": {
            "en": "Built-in mask Subsystem templates shipped with flode.",
            "ja": "flode 同梱のマスク Subsystem テンプレート集。",
        },
        "entries": [
            {
                "id": "pid_controller",
                "display_name": "PID Controller",
                "description": "PID controller (Kp, Ki, Kd) with single error input.",
                "category_suffix": "controllers",
                "display_name_i18n": {
                    "en": "PID Controller",
                    "ja": "PID コントローラ",
                },
                "description_i18n": {
                    "en": "PID controller (Kp, Ki, Kd) with single error input.",
                    "ja": "PID コントローラ (Kp / Ki / Kd、誤差 1 入力)。",
                },
                "subsystem": pid_dict,
            },
            {
                "id": "first_order_plant",
                "display_name": "First-Order Plant",
                "description": "G(s) = K / (tau*s + 1).",
                "category_suffix": "plants",
                "display_name_i18n": {
                    "en": "First-Order Plant",
                    "ja": "1 次遅れプラント",
                },
                "description_i18n": {
                    "en": "G(s) = K / (tau*s + 1).",
                    "ja": "G(s) = K / (tau*s + 1)。",
                },
                "subsystem": fop_dict,
            },
            {
                "id": "second_order_plant",
                "display_name": "Second-Order Plant",
                "description": "G(s) = K / (a*s^2 + b*s + 1).",
                "category_suffix": "plants",
                "display_name_i18n": {
                    "en": "Second-Order Plant",
                    "ja": "2 次プラント",
                },
                "description_i18n": {
                    "en": "G(s) = K / (a*s^2 + b*s + 1).",
                    "ja": "G(s) = K / (a*s^2 + b*s + 1)。",
                },
                "subsystem": sop_dict,
            },
        ],
    }

    out_path.write_text(
        json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {out_path}  ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
