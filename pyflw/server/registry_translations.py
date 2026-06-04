"""ADR-0028: Block class registry の i18n 翻訳テーブル。

集中管理方式 (ADR-0028 §Decision Option 1) で、各 built-in Block の
``display_name`` と ``docstring_summary`` の en/ja 翻訳を 1 か所に集約する。
``registry.build_metadata()`` から ``get_translations()`` 経由で参照される。

カバー範囲: ``_BUILTIN_METADATA`` (registry.py) に登録された全 Block class。
カバレッジ完全性は ``tests/server/test_registry_translations.py`` で
継続的に検証する (新規ブロック追加時の翻訳漏れを CI で検出)。

3rd-party 拡張ブロック (= ``_BUILTIN_METADATA`` 未登録) の翻訳サポートは Phase 5+
で別 ADR (``pyflw.register_block_translations()`` API 等) として扱う。本テーブル
未登録の type_path は ``inspect.getdoc()`` の 1 行目を ``docstring_summary`` に、
class attribute (`_block_display_name`) を ``display_name`` に使う既存挙動に
フォールバックする (= 後方互換)。
"""

from __future__ import annotations

from typing import Final, Literal

#: サポート言語コード (ADR-0024 §Decision §(3) と一致)。
Locale = Literal["en", "ja"]

SUPPORTED_LOCALES: Final[tuple[Locale, ...]] = ("en", "ja")

#: 1 ブロックの 1 言語あたりの翻訳エントリ。
#: ``display_name``: 短い名詞 (英大文字始まり / 句点なし)
#: ``docstring_summary``: 1 行説明 (句点あり、数式は両言語共通の半角)
_BlockEntry = dict[str, str]
_LocaleMap = dict[Locale, _BlockEntry]


_BLOCK_TRANSLATIONS: dict[str, _LocaleMap] = {
    # ----- sources (6) ----------------------------------------------------
    "pyflw.blocks.sources.Constant": {
        "en": {
            "display_name": "Constant",
            "docstring_summary": "Constant value source y(t) = value.",
        },
        "ja": {
            "display_name": "定数",
            "docstring_summary": "定数値ソース y(t) = value。",
        },
    },
    "pyflw.blocks.sources.Step": {
        "en": {
            "display_name": "Step",
            "docstring_summary": "Step source: 0 before t = step_time, then final_value.",
        },
        "ja": {
            "display_name": "ステップ",
            "docstring_summary": "ステップ信号: t < step_time でゼロ、以降 final_value。",
        },
    },
    "pyflw.blocks.sources.Sine": {
        "en": {
            "display_name": "Sine",
            "docstring_summary": "Sine wave y(t) = amplitude * sin(2*pi*frequency*t + phase) + bias.",
        },
        "ja": {
            "display_name": "正弦波",
            "docstring_summary": "正弦波 y(t) = amplitude * sin(2*pi*frequency*t + phase) + bias。",
        },
    },
    "pyflw.blocks.sources.Ramp": {
        "en": {
            "display_name": "Ramp",
            "docstring_summary": "Ramp source y(t) = slope * (t - start_time) for t >= start_time.",
        },
        "ja": {
            "display_name": "ランプ",
            "docstring_summary": "ランプ信号 y(t) = slope * (t - start_time) (t >= start_time)。",
        },
    },
    "pyflw.blocks.sources.Clock": {
        "en": {
            "display_name": "Clock",
            "docstring_summary": "Clock source y(t) = t (current simulation time).",
        },
        "ja": {
            "display_name": "クロック",
            "docstring_summary": "シミュレーション時刻ソース y(t) = t。",
        },
    },
    "pyflw.blocks.sources.PulseGenerator": {
        "en": {
            "display_name": "Pulse Generator",
            "docstring_summary": "Periodic rectangular pulse with configurable period and duty cycle.",
        },
        "ja": {
            "display_name": "パルス発生器",
            "docstring_summary": "周期と Duty 比を指定できる矩形パルス信号。",
        },
    },
    # SPEC-0010 / ADR-0059 (v5.3.0): Random / Noise source (Wave 1 第 3 弾、最終)
    "pyflw.blocks.random_source.RandomSource": {
        "en": {
            "display_name": "Random Source",
            "docstring_summary": (
                "Stochastic source: draw a random sample at each sample_time "
                "and hold (uniform / gaussian; seed for determinism)."
            ),
        },
        "ja": {
            "display_name": "乱数源",
            "docstring_summary": (
                "サンプル時刻で乱数を引いて hold する確率的入力 "
                "(uniform / gaussian、seed で決定性)。"
            ),
        },
    },
    # ----- mathops (8) ---------------------------------------------------
    "pyflw.blocks.mathops.Gain": {
        "en": {
            "display_name": "Gain",
            "docstring_summary": "Scalar gain y(t) = k * u(t).",
        },
        "ja": {
            "display_name": "ゲイン",
            "docstring_summary": "スカラーゲイン y(t) = k * u(t)。",
        },
    },
    "pyflw.blocks.mathops.Sum": {
        "en": {
            "display_name": "Sum",
            "docstring_summary": "Weighted sum of inputs with per-port +/- signs.",
        },
        "ja": {
            "display_name": "加算",
            "docstring_summary": "符号付き入力の重み付き和 (ポートごとに +/- を指定)。",
        },
    },
    # v0.35.0: Add ブロック (Sum の矩形版、機能同等)
    "pyflw.blocks.mathops.Add": {
        "en": {
            "display_name": "Add",
            "docstring_summary": "Sum block in rectangular shape (signed sum with per-port +/-).",
        },
        "ja": {
            "display_name": "加算 (矩形)",
            "docstring_summary": "符号付き加算 (矩形版、機能は Sum と同じ)。",
        },
    },
    "pyflw.blocks.mathops.Product": {
        "en": {
            "display_name": "Product",
            "docstring_summary": "Element-wise product of all input ports.",
        },
        "ja": {
            "display_name": "乗算",
            "docstring_summary": "全入力ポートの要素ごとの積。",
        },
    },
    "pyflw.blocks.mathops.Saturation": {
        "en": {
            "display_name": "Saturation",
            "docstring_summary": "Clamp input to the range [lower, upper].",
        },
        "ja": {
            "display_name": "飽和",
            "docstring_summary": "入力を [lower, upper] の範囲にクランプ。",
        },
    },
    "pyflw.blocks.mathops.Abs": {
        "en": {
            "display_name": "Abs",
            "docstring_summary": "Absolute value y(t) = |u(t)|.",
        },
        "ja": {
            "display_name": "絶対値",
            "docstring_summary": "絶対値 y(t) = |u(t)|。",
        },
    },
    "pyflw.blocks.mathops.Sign": {
        "en": {
            "display_name": "Sign",
            "docstring_summary": "Signum y(t) = sign(u(t)) in {-1, 0, +1}.",
        },
        "ja": {
            "display_name": "符号",
            "docstring_summary": "符号関数 y(t) = sign(u(t)) で {-1, 0, +1}。",
        },
    },
    "pyflw.blocks.mathops.MinMax": {
        "en": {
            "display_name": "MinMax",
            "docstring_summary": "Element-wise min or max of n inputs (mode selectable).",
        },
        "ja": {
            "display_name": "最小・最大",
            "docstring_summary": "n 入力の要素ごとの最小値または最大値 (モード切替)。",
        },
    },
    "pyflw.blocks.mathops.Divide": {
        "en": {
            "display_name": "Divide",
            "docstring_summary": "Multiply / divide inputs based on per-port * or / signs.",
        },
        "ja": {
            "display_name": "除算",
            "docstring_summary": "ポートごとに * または / を指定して入力を乗除算。",
        },
    },
    # SPEC-0002 / ADR-0053 (v0.36.0): Phase 2 送り Math 系 5 ブロック第 1 弾
    "pyflw.blocks.mathops.MathFunction": {
        "en": {
            "display_name": "Math Function",
            "docstring_summary": "Compute exp / log / sqrt / pow etc. Choose with `function`.",
        },
        "ja": {
            "display_name": "数学関数",
            "docstring_summary": "exp / log / sqrt / pow 等を計算 (function で関数を選択)。",
        },
    },
    "pyflw.blocks.mathops.TrigFunction": {
        "en": {
            "display_name": "Trig Function",
            "docstring_summary": "Compute sin / cos / atan2 etc. in radians (choose with `function`).",
        },
        "ja": {
            "display_name": "三角関数",
            "docstring_summary": "sin / cos / atan2 等を radian で計算 (function で関数を選択)。",
        },
    },
    "pyflw.blocks.mathops.DeadZone": {
        "en": {
            "display_name": "Dead Zone",
            "docstring_summary": "Zero output within [lower, upper], pass through with offset outside.",
        },
        "ja": {
            "display_name": "不感帯",
            "docstring_summary": "[lower, upper] 内ではゼロ、範囲外はオフセットを引いた値を出力。",
        },
    },
    "pyflw.blocks.mathops.CompareToConstant": {
        "en": {
            "display_name": "Compare To Constant",
            "docstring_summary": "Compare input to a constant: y = (u op const) ? 1.0 : 0.0.",
        },
        "ja": {
            "display_name": "定数比較",
            "docstring_summary": "入力を定数と比較 y = (u op const) ? 1.0 : 0.0。",
        },
    },
    "pyflw.blocks.mathops.CompareToZero": {
        "en": {
            "display_name": "Compare To Zero",
            "docstring_summary": "Compare input to zero: y = (u op 0) ? 1.0 : 0.0.",
        },
        "ja": {
            "display_name": "ゼロ比較",
            "docstring_summary": "入力をゼロと比較 y = (u op 0) ? 1.0 : 0.0。",
        },
    },
    # SPEC-0013 / ADR-0059 (v5.6.0): Rounding (Wave 2 第 2 弾)
    "pyflw.blocks.rounding.Rounding": {
        "en": {
            "display_name": "Rounding",
            "docstring_summary": "Round to integer: floor / ceil / round / trunc (choose with `mode`).",
        },
        "ja": {
            "display_name": "丸め",
            "docstring_summary": "整数化 floor / ceil / round / trunc (mode で選択)。",
        },
    },
    # ----- lookup (1) -----------------------------------------------------
    # SPEC-0008 / ADR-0059 (v5.1.0): Lookup Tables 新カテゴリ第 1 弾
    "pyflw.blocks.lookup.LookupTable1D": {
        "en": {
            "display_name": "Lookup Table (1-D)",
            "docstring_summary": (
                "Interpolate y(t) from a 1-D breakpoint array and table values "
                "(linear / nearest / flat; extrapolation clip / linear / error)."
            ),
        },
        "ja": {
            "display_name": "ルックアップテーブル (1-D)",
            "docstring_summary": (
                "1 次元ブレークポイント配列とテーブル値で y(t) を補間 "
                "(linear / nearest / flat、外挿は clip / linear / error)。"
            ),
        },
    },
    # ----- userfunc (1) ---------------------------------------------------
    # SPEC-0009 / ADR-0059 (v5.2.0): User-Defined Functions 新カテゴリ第 1 弾
    "pyflw.blocks.userfunc.Fcn": {
        "en": {
            "display_name": "Fcn",
            "docstring_summary": (
                "Evaluate an arbitrary expression y(t, u) "
                "(numpy funcs like sin/cos/exp and u[i]/t allowed)."
            ),
        },
        "ja": {
            "display_name": "数式ブロック",
            "docstring_summary": (
                "任意式 y(t, u) を評価 (sin/cos/exp 等の numpy 関数と u[i]/t を使用可)。"
            ),
        },
    },
    # ----- continuous (5) -------------------------------------------------
    "pyflw.blocks.continuous.Integrator": {
        "en": {
            "display_name": "Integrator",
            "docstring_summary": "Continuous integrator x_dot = u, y = x.",
        },
        "ja": {
            "display_name": "積分器",
            "docstring_summary": "連続時間積分器 x_dot = u、y = x。",
        },
    },
    "pyflw.blocks.continuous.Derivative": {
        "en": {
            "display_name": "Derivative",
            "docstring_summary": "First-order high-pass approximation of d/dt.",
        },
        "ja": {
            "display_name": "微分器",
            "docstring_summary": "1 次ハイパスフィルタによる微分の近似。",
        },
    },
    "pyflw.blocks.continuous.TransferFunction": {
        "en": {
            "display_name": "Transfer Fcn",
            "docstring_summary": "SISO continuous transfer function H(s) = num(s) / den(s).",
        },
        "ja": {
            "display_name": "伝達関数",
            "docstring_summary": "SISO 連続伝達関数 H(s) = num(s) / den(s)。",
        },
    },
    "pyflw.blocks.continuous.StateSpace": {
        "en": {
            "display_name": "State Space",
            "docstring_summary": "Continuous LTI state-space x_dot = A x + B u, y = C x + D u.",
        },
        "ja": {
            "display_name": "状態空間",
            "docstring_summary": "連続 LTI 状態空間 x_dot = A x + B u、y = C x + D u。",
        },
    },
    "pyflw.blocks.continuous.MimoTransferFunction": {
        "en": {
            "display_name": "MIMO TF",
            "docstring_summary": "MIMO continuous transfer function H(s) = N(s) / d(s) (common denominator).",
        },
        "ja": {
            "display_name": "MIMO 伝達関数",
            "docstring_summary": "MIMO 連続伝達関数 H(s) = N(s) / d(s) (共通分母)。",
        },
    },
    # ----- discrete (6) ---------------------------------------------------
    "pyflw.blocks.discrete.UnitDelay": {
        "en": {
            "display_name": "Unit Delay",
            "docstring_summary": "One-sample delay y(t_k) = u(t_{k-1}).",
        },
        "ja": {
            "display_name": "単位遅延",
            "docstring_summary": "1 サンプル遅延 y(t_k) = u(t_{k-1})。",
        },
    },
    "pyflw.blocks.discrete.DiscreteIntegrator": {
        "en": {
            "display_name": "Discrete Integrator",
            "docstring_summary": "Discrete-time accumulator with selectable forward / backward / trapezoidal method.",
        },
        "ja": {
            "display_name": "離散積分器",
            "docstring_summary": "離散時間累積器 (前進 / 後退 / 台形法を選択可能)。",
        },
    },
    "pyflw.blocks.discrete.ZeroOrderHoldDirect": {
        "en": {
            "display_name": "ZOH",
            "docstring_summary": "Zero-order hold with direct feedthrough (y = u at each sample step).",
        },
        "ja": {
            "display_name": "ZOH",
            "docstring_summary": "直達経路付きゼロ次ホールド (各サンプルステップで y = u)。",
        },
    },
    "pyflw.blocks.discrete.RateTransition": {
        "en": {
            "display_name": "Rate Transition",
            "docstring_summary": "Multirate bridge between blocks with different sample times (zoh / delay / auto).",
        },
        "ja": {
            "display_name": "レート変換",
            "docstring_summary": "異なるサンプル時間のブロック間を橋渡しするマルチレート変換 (zoh / delay / auto)。",
        },
    },
    "pyflw.blocks.discrete.DiscreteStateSpace": {
        "en": {
            "display_name": "Discrete State Space",
            "docstring_summary": "Discrete LTI state-space x[k+1] = A x[k] + B u[k], y[k] = C x[k] + D u[k].",
        },
        "ja": {
            "display_name": "離散状態空間",
            "docstring_summary": "離散 LTI 状態空間 x[k+1] = A x[k] + B u[k]、y[k] = C x[k] + D u[k]。",
        },
    },
    "pyflw.blocks.discrete.DiscreteTransferFunction": {
        "en": {
            "display_name": "Discrete Transfer Fcn",
            "docstring_summary": "SISO discrete transfer function H(z) = num(z) / den(z).",
        },
        "ja": {
            "display_name": "離散伝達関数",
            "docstring_summary": "SISO 離散伝達関数 H(z) = num(z) / den(z)。",
        },
    },
    # ----- logic (2) ------------------------------------------------------
    "pyflw.blocks.logic.RelationalOperator": {
        "en": {
            "display_name": "Relational",
            "docstring_summary": "Compare two inputs with ==, !=, <, <=, >, >=.",
        },
        "ja": {
            "display_name": "関係演算",
            "docstring_summary": "2 入力を ==、!=、<、<=、>、>= で比較。",
        },
    },
    # SPEC-0012 / ADR-0059 (v5.5.0): Wave 2 第 1 弾 = stateful discontinuities
    "pyflw.blocks.discontinuities.RateLimiter": {
        "en": {
            "display_name": "Rate Limiter",
            "docstring_summary": (
                "Limit input slew rate (rising / falling) sample-by-sample, "
                "holding between samples."
            ),
        },
        "ja": {
            "display_name": "変化率リミッタ",
            "docstring_summary": (
                "入力の変化率 (rising / falling) をサンプル時刻で制限し、"
                "中間時刻は前値を hold。"
            ),
        },
    },
    "pyflw.blocks.discontinuities.Relay": {
        "en": {
            "display_name": "Relay",
            "docstring_summary": (
                "Hysteresis ON / OFF switch: state flips when input crosses "
                "switch_on_point / switch_off_point thresholds."
            ),
        },
        "ja": {
            "display_name": "リレー",
            "docstring_summary": (
                "ヒステリシス付き ON / OFF スイッチ: "
                "switch_on_point / switch_off_point でしきい値遷移。"
            ),
        },
    },
    "pyflw.blocks.logic.LogicalOperator": {
        "en": {
            "display_name": "Logical",
            "docstring_summary": "Logical AND / OR / XOR / NAND / NOR / XNOR / NOT over n inputs.",
        },
        "ja": {
            "display_name": "論理演算",
            "docstring_summary": "n 入力に対する AND / OR / XOR / NAND / NOR / XNOR / NOT 論理演算。",
        },
    },
    # ----- routing (3) ----------------------------------------------------
    "pyflw.blocks.routing.Switch": {
        "en": {
            "display_name": "Switch",
            "docstring_summary": "Select input 0 or 2 based on threshold criterion on input 1.",
        },
        "ja": {
            "display_name": "スイッチ",
            "docstring_summary": "入力 1 のしきい値判定で入力 0 または 2 を出力。",
        },
    },
    "pyflw.blocks.routing.Mux": {
        "en": {
            "display_name": "Mux",
            "docstring_summary": "Concatenate n scalar inputs into a single (n,) vector output.",
        },
        "ja": {
            "display_name": "Mux",
            "docstring_summary": "n 個のスカラー入力を 1 本の (n,) ベクトル出力に統合。",
        },
    },
    "pyflw.blocks.routing.Demux": {
        "en": {
            "display_name": "Demux",
            "docstring_summary": "Split a single (n,) vector input into n scalar outputs.",
        },
        "ja": {
            "display_name": "Demux",
            "docstring_summary": "1 本の (n,) ベクトル入力を n 個のスカラー出力に分割。",
        },
    },
    # SPEC-0003 / ADR-0055: tag ベース仮想配線
    "pyflw.blocks.routing.Goto": {
        "en": {
            "display_name": "Goto",
            "docstring_summary": "Publish input under a tag for virtual wiring to From blocks.",
        },
        "ja": {
            "display_name": "Goto",
            "docstring_summary": "入力を tag に紐付けて公開し、対応する From ブロックへ仮想配線する。",
        },
    },
    "pyflw.blocks.routing.From": {
        "en": {
            "display_name": "From",
            "docstring_summary": "Receive signal from a Goto block with matching tag (Local / Global).",
        },
        "ja": {
            "display_name": "From",
            "docstring_summary": "同じ tag を持つ Goto ブロックの信号を受信 (Local / Global)。",
        },
    },
    # SPEC-0014 / ADR-0059 (v5.7.0): Wave 2 第 3 弾 = routing 拡張
    "pyflw.blocks.routing.MultiportSwitch": {
        "en": {
            "display_name": "Multiport Switch",
            "docstring_summary": (
                "Select one of n_choices data inputs by selector index (u[0])."
            ),
        },
        "ja": {
            "display_name": "マルチポートスイッチ",
            "docstring_summary": (
                "selector index (u[0]) で n_choices 個のデータ入力から 1 つを選択。"
            ),
        },
    },
    "pyflw.blocks.routing.Merge": {
        "en": {
            "display_name": "Merge",
            "docstring_summary": (
                "Priority merge: output first input that differs from initial_value."
            ),
        },
        "ja": {
            "display_name": "マージ",
            "docstring_summary": (
                "優先度マージ: initial_value と異なる最初の入力を出力する。"
            ),
        },
    },
    # ----- sinks (4) ------------------------------------------------------
    "pyflw.blocks.sinks.Scope": {
        "en": {
            "display_name": "Scope",
            "docstring_summary": "Record signal time series and visualise via plot().",
        },
        "ja": {
            "display_name": "Scope",
            "docstring_summary": "信号の時系列を記録し plot() で可視化。",
        },
    },
    "pyflw.blocks.sinks.Display": {
        "en": {
            "display_name": "Display",
            "docstring_summary": "Show the latest sample as a numeric readout on the block face.",
        },
        "ja": {
            "display_name": "Display",
            "docstring_summary": "最新サンプルをブロック上に数値表示。",
        },
    },
    "pyflw.blocks.sinks.XYGraph": {
        "en": {
            "display_name": "XY Graph",
            "docstring_summary": "Parametric x-y plot of inputs 0 (x) and 1 (y).",
        },
        "ja": {
            "display_name": "XY グラフ",
            "docstring_summary": "入力 0 (x) と 1 (y) のパラメトリックプロット。",
        },
    },
    "pyflw.blocks.sinks.Terminator": {
        "en": {
            "display_name": "Terminator",
            "docstring_summary": "Discard the input signal (suppresses unconnected output warnings).",
        },
        "ja": {
            "display_name": "Terminator",
            "docstring_summary": "入力信号を破棄 (未接続出力の警告を抑制)。",
        },
    },
    # ----- subsystems (3) -------------------------------------------------
    "pyflw.subsystems.subsystem.Subsystem": {
        "en": {
            "display_name": "Subsystem",
            "docstring_summary": "Atomic subsystem grouping inner blocks with Inport / Outport boundaries.",
        },
        "ja": {
            "display_name": "Subsystem",
            "docstring_summary": "Inport / Outport で境界を区切った内部ブロック群を 1 つのブロックにまとめる Atomic Subsystem。",
        },
    },
    "pyflw.subsystems.ports.Inport": {
        "en": {
            "display_name": "Inport",
            "docstring_summary": "Subsystem boundary input port (only valid inside a Subsystem).",
        },
        "ja": {
            "display_name": "Inport",
            "docstring_summary": "Subsystem 境界の入力ポート (Subsystem 内部でのみ使用)。",
        },
    },
    "pyflw.subsystems.ports.Outport": {
        "en": {
            "display_name": "Outport",
            "docstring_summary": "Subsystem boundary output port (only valid inside a Subsystem).",
        },
        "ja": {
            "display_name": "Outport",
            "docstring_summary": "Subsystem 境界の出力ポート (Subsystem 内部でのみ使用)。",
        },
    },
    # ADR-0058: Subsystem behavior modifier control blocks。Subsystem 内部に置く
    # ことで親の発火 / 有効化セマンティクスを修飾する境界ブロック。
    "pyflw.subsystems.control_blocks.Trigger": {
        "en": {
            "display_name": "Trigger",
            "docstring_summary": (
                "Place inside a Subsystem to fire it on trigger edges "
                "(rising / falling / either)."
            ),
        },
        "ja": {
            "display_name": "Trigger",
            "docstring_summary": (
                "Subsystem 内部に置くと、トリガー信号のエッジ "
                "(rising / falling / either) で親 Subsystem を発火する境界ブロック。"
            ),
        },
    },
    "pyflw.subsystems.control_blocks.Enable": {
        "en": {
            "display_name": "Enable",
            "docstring_summary": (
                "Place inside a Subsystem to gate execution by an enable signal "
                "(state / output policy: held or reset)."
            ),
        },
        "ja": {
            "display_name": "Enable",
            "docstring_summary": (
                "Subsystem 内部に置くと、enable 信号が真の間だけ親 Subsystem を"
                "動作させる境界ブロック (state / output policy: held / reset)。"
            ),
        },
    },
}


def get_translations(type_path: str) -> _LocaleMap:
    """``type_path`` に対応する翻訳辞書を返す。

    Args:
        type_path: ``"pyflw.blocks.sources.Constant"`` のような完全 type path。

    Returns:
        ``{"en": {"display_name": ..., "docstring_summary": ...}, "ja": {...}}``。
        未登録の type_path には空 dict ``{}`` を返し、registry.py 側で
        ``inspect.getdoc()`` フォールバックに任せる (= 3rd-party 拡張ブロックは
        当面 en 固定で動作)。
    """
    return _BLOCK_TRANSLATIONS.get(type_path, {})


def all_registered_type_paths() -> set[str]:
    """``_BLOCK_TRANSLATIONS`` に登録済の全 type_path 集合を返す。

    pytest のカバレッジ検証 (``test_all_builtin_blocks_have_translations``) で
    ``_BUILTIN_METADATA.keys()`` との差集合を取って翻訳漏れを検出する。
    """
    return set(_BLOCK_TRANSLATIONS.keys())
