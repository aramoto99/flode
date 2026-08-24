# flode

[![CI](https://github.com/aramoto99/flode/actions/workflows/ci.yml/badge.svg)](https://github.com/aramoto99/flode/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**flode** (**FLO**w + o**DE**) はブロック線図ベースの動的システムシミュレータです。
ブラウザ上でブロックを配線してモデルを組み、連続系・離散系・その混在系を
`scipy.solve_ivp` (既定 RK45) でシミュレートします。

## 特徴

- **Web ベースのブロック線図エディタ** — ブロックをドラッグして配線、inspector
  パネルでパラメータ編集、実行するとライブプロット。ブラウザだけで完結
- **50+ の組み込みブロック** (下記 [ブロックライブラリ](#ブロックライブラリ))
- **連続・離散・ハイブリッドシミュレーション** (代数ループ自動検出)
- **Subsystem による階層化** (内部の Trigger / Enable ブロックで実行制御)
- **`@block` デコレータ** — Python 関数を数行でカスタムブロック化
- **解析機能** — 線形化、Bode / Nyquist、固有値による安定判別、根軌跡
- **JAX による codegen + autodiff** (opt-in、実験的)
- **モデルはプレーン JSON** (`.flw.json`) — バージョン管理と相性が良い

## インストール

前提: **Python 3.11+**。ソースから入れる場合は **Node.js 20+** も必要
(frontend を一度ローカルでビルドするため)。

```bash
git clone https://github.com/aramoto99/flode.git
cd flode

# frontend をビルド (flode/server/static/ に出力される)
cd flode/web/frontend
npm install
npm run build
cd ../../..

pip install -e .
```

[GitHub Releases](https://github.com/aramoto99/flode/releases) 添付の
prebuilt wheel なら frontend 同梱のため Node 不要
(`pip install flode-<version>-py3-none-any.whl`)。
PyPI には未公開のため `pip install flode` はまだ使えません。

オプション extras (`pip install -e ".[control,dev]"` のように併用可):

| extras | 内容 |
|---|---|
| `[control]` | python-control による Bode / Nyquist / 根軌跡 |
| `[codegen]` | JAX (CPU) — `Simulator.compile()` / `linearize(method="jax")` |
| `[gpu]` | JAX GPU backend (NVIDIA CUDA 12 / Linux x86_64 のみ) |
| `[dev]` | pytest, ruff, mypy, sphinx |

## 使い方

### Web GUI

```bash
flode
```

サーバが起動し、既定ブラウザで UI が自動的に開きます (ポートが使用中なら
空きポートへ自動フォールバック)。

```bash
flode --workspace ./my-models --port 8770   # workspace とポートを指定
flode --no-browser                          # ブラウザを開かない
```

workspace は `.flw.json` を置くただのディレクトリです。サーバは既定で
`127.0.0.1` に bind し、workspace 検索 API は `.env*` / `id_rsa` / `.ssh/`
等の credential パスを常に除外します。

### Python API

```python
from flode import Simulator
from flode.blocks import Constant, Gain, Integrator, Scope

sim = Simulator(t_end=10.0, dt=0.01)

src   = sim.add(Constant(value=1.0, id="src"))
gain  = sim.add(Gain(k=2.0, id="gain"))
integ = sim.add(Integrator(x0=0.0, id="integ"))
scope = sim.add(Scope(n_inputs=1, id="scope"))

sim.connect(src, gain)
sim.connect(gain, integ)
sim.connect(integ, scope)

sim.run()
scope.plot(show=True)
```

2 次系の完全な例は `examples/spring_mass_damper.py` を参照してください。

## ブロックライブラリ

| カテゴリ | ブロック |
|-----------------|---------------------------------------------------------------------------|
| Sources         | Constant, Step, Sine, Ramp, Clock, PulseGenerator, RandomSource          |
| Sinks           | Scope, Terminator, Display, XYGraph                                       |
| Continuous      | Integrator, StateSpace, TransferFunction, MimoTransferFunction, Derivative, TransportDelay |
| Discrete        | UnitDelay, DiscreteIntegrator, ZeroOrderHoldDirect, DiscreteStateSpace, DiscreteTransferFunction, RateTransition |
| Math            | Gain, Sum, Add, Product, Divide, Saturation, Abs, Sign, MinMax, MathFunction, TrigFunction, Rounding |
| Discontinuities | DeadZone, Relay, RateLimiter, CompareToConstant, CompareToZero            |
| Lookup          | LookupTable1D, LookupTable2D, LookupTableND, Prelookup, InterpolationUsingPrelookup |
| Logic           | RelationalOperator, LogicalOperator                                       |
| Routing         | Switch, MultiportSwitch, Mux, Demux, Merge, Goto, From                    |
| User Function   | Fcn (任意式 `y = f(t, u)`、AST whitelist で安全に評価)                    |
| Subsystem       | Subsystem (内部の Trigger / Enable ブロックで実行制御)                    |
| Control         | Inport, Outport, Trigger, Enable                                          |

多くは `flode.blocks` から直接 import できます (一部の GUI 向け変種、例えば
`Add` は `flode.blocks.mathops` 配下)。API リファレンスは
`sphinx-build -b html docs docs/_build` でビルドできます。

## `@block` デコレータ

`Block` を継承せずに、関数 1 つでカスタムブロックを定義できます:

```python
import numpy as np
from flode import block

@block(states=1)
def my_integrator(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
    y = x[0]
    x_dot = np.array([u])
    return y, x_dot
```

`output` / `derivative` / `update` を分けたい場合はクラス形式 (`@block` を
クラスに適用) も使えます。

## 解析

`flode.linearize()` はモデルを動作点まわりで数値線形化し、状態空間行列
`(A, B, C, D)` を持つ `LinearSystem` を返します:

```python
from flode import linearize

ls = linearize(sim)
print(ls.A.shape, ls.eigenvalues(), ls.is_stable())
```

`eigenvalues()` / `is_stable()` は numpy のみで動作し、`bode()` /
`nyquist()` / `root_locus()` は `flode[control]` extras が必要です。

## Codegen + Autodiff (JAX、opt-in)

`Simulator.compile(backend="jax")` と `linearize(method="jax")` は対象ブロック
を `jax.jit` / `jax.jacfwd` でトレースし、XLA コンパイルと機械精度 Jacobian を
提供します (`flode[codegen]` extras が必要)。`compile()` を呼ばない限り、
既定の numpy 実行パスには一切影響しません。

まだ実験的機能で、対応ブロックは `Constant` / `Step` / `Sine` / `Ramp` /
`Clock` / `Gain` / `Sum` / `Integrator` + sink 系のみです。それ以外を含む
モデルは `BlockSpecError` になります。

## 設定

`--workspace` / `--port` 等の既定値は `~/.flode/config.toml`
(Windows は `%USERPROFILE%\.flode\config.toml`) に永続化できます。
コメント付き雛形は `flode --generate-config` で生成されます。
優先順位は **CLI 引数 > config ファイル > 既定値** です。

## バージョニング

flode は [ZeroVer](https://0ver.org/) を採用しており、`0.x` に留まり続けます。
**minor** は機能追加または破壊的変更、**patch** は修正です。リリースノートは
`CHANGELOG.md` を参照してください。

## 開発

```bash
pytest -ra                                  # テスト
ruff check flode tests examples             # lint (CI と同一対象)
ruff format --check flode tests examples    # format チェック
mypy flode                                  # 型チェック
sphinx-build -W -b html docs docs/_build    # ドキュメント (CI は warning を error 扱い)
```

frontend の開発手順 (Vite dev server) は `flode/web/frontend/README.md` を
参照してください。

## ライセンス

MIT — `LICENSE` を参照。
