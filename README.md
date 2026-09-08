# flode

[![CI](https://github.com/aramoto99/flode/actions/workflows/ci.yml/badge.svg)](https://github.com/aramoto99/flode/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**flode** (**FLO**w + o**DE**) はブロック線図ベースの動的システムシミュレータです。
ブラウザ上でブロックを配線してモデルを組み、連続系・離散系・その混在系を
`scipy.solve_ivp` (既定 RK45) でシミュレートします。

- **Web ベースのエディタ** — ドラッグ&ドロップで配線、inspector でパラメータ編集、ライブプロット。ブロック名は日本語 OK (rename は F2 / ダブルクリック、空白・記号は不可で `_` を使用)
- **50+ の組み込みブロック**、Subsystem による階層化 (Trigger / Enable)
- **`@block` デコレータ** — Python 関数を数行でカスタムブロック化
- **解析機能** — 線形化、Bode / Nyquist、安定判別、根軌跡
- **モデルはプレーン JSON** (`.flw.json`) — バージョン管理と相性が良い

## インストール

前提: **Python 3.11+**。ソースから入れる場合は **Node.js 20+** も必要です。

```bash
git clone https://github.com/aramoto99/flode.git
cd flode

# frontend をビルド (flode/server/static/ に出力される)
cd flode/web/frontend && npm install && npm run build && cd ../../..

pip install -e .
```

[GitHub Releases](https://github.com/aramoto99/flode/releases) の prebuilt wheel
なら frontend 同梱のため Node 不要です。PyPI には未公開のため
`pip install flode` はまだ使えません。

オプション extras: `[control]` (Bode / Nyquist / 根軌跡)、
`[dev]` (pytest, ruff, mypy, sphinx)。

## 使い方

### Web GUI

```bash
flode                                       # サーバ起動 + ブラウザが自動で開く
flode --workspace ./my-models --port 8770   # workspace とポートを指定
flode --no-browser                          # ブラウザを開かない
```

workspace は `.flw.json` を置くただのディレクトリです。サーバは既定で
`127.0.0.1` に bind し、workspace 検索は credential パス (`.env*` / `.ssh/` 等)
を常に除外します。既定値は `flode --generate-config` で生成される
`~/.flode/config.toml` に永続化できます (優先順位: CLI > config > 既定値)。

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
| Math            | Gain, Sum, Add, Product, Divide, Saturation, Abs, Sign, MinMax, MathFunction, TrigFunction, Rounding, Cast |
| Discontinuities | DeadZone, Relay, RateLimiter, CompareToConstant, CompareToZero            |
| Lookup          | LookupTable1D, LookupTable2D, LookupTableND, Prelookup, InterpolationUsingPrelookup |
| Logic           | RelationalOperator, LogicalOperator                                       |
| Routing         | Switch, MultiportSwitch, Mux, Demux, Merge, Goto, From                    |
| User Function   | Fcn (任意式 `y = f(t, u)`、AST whitelist で安全に評価)、PythonFunction (`@block` 形の Python ソースを GUI から記述、**サンドボックスなし**) |
| Subsystem       | Subsystem (内部の Trigger / Enable ブロックで実行制御)                    |
| Control         | Inport, Outport, Trigger, Enable                                          |

API リファレンスは `sphinx-build -b html docs docs/_build` でビルドできます。

## 解析・カスタムブロック

`flode.linearize()` はモデルを動作点まわりで数値線形化し、`(A, B, C, D)` を持つ
`LinearSystem` を返します。`eigenvalues()` / `is_stable()` は numpy のみで動作し、
`bode()` / `nyquist()` / `root_locus()` には `flode[control]` が必要です。

```python
from flode import linearize

ls = linearize(sim)
print(ls.A.shape, ls.eigenvalues(), ls.is_stable())
```

カスタムブロックは `@block` デコレータで関数 1 つから定義できます:

```python
@block(states=1)
def my_integrator(t, x, u):
    return x[0], np.array([u])   # (出力, 状態微分)
```

同じ `@block` 形のソースを GUI から書けるのが **Python Function** ブロックです
(パレット「User Function」)。ポート数・状態数・パラメータはコードから自動で決まり、
パラメータは Inspector に行として現れます。

> **セキュリティ**: Python Function はサンドボックスされません。このブロックを
> 含むモデルを実行することは、その中のコードを自分の権限で実行することと同義です
> (モデルを開くだけでは実行されず、初回実行前に確認ダイアログが出ます)。
> `127.0.0.1` 以外に bind したサーバーでは `flode --allow-python-blocks` を付けない
> 限り実行が拒否されます。式で書けるロジックには `Fcn` を使ってください。

### 信号の dtype (SM-D、v0.55.0〜)

`Cast` / `Constant` の **`dtype`** param で numpy dtype
(`float64` / `int32` / `int64` / `uint8` / `bool`) を宣言すると、
下流の信号が**実際にその型として計算**されます (numpy ネイティブ意味論:
整数のオーバーフローは wrap、`bool + bool` は論理和、整数の floor 除算 0 割りは
`0`)。dtype を宣言していないモデルは従来どおり全経路 float64 で、結果は
bit 単位で不変です。Inspector の「信号型」セクションに各ポートの解決結果が
表示されます。

型概念は `dtype` の 1 系統のみです (v0.56.0 で旧 `output_type` を撤去):

- `Cast(dtype=...)` は**常に実変換** (`astype` 相当)。float → 整数は
  ゼロ方向切り捨て、nan → 0、±inf → 飽和。既定は `"float64"`
- `Constant(dtype=...)` の既定は `"auto"` (未宣言 = ただの float64 定数)
- 偶数丸めが欲しい場合は `Rounding(mode="round")`、0/1 化には
  `CompareToZero(op="!=")` を使う (旧 `output_type="int"` / `"bool"` の等価)。
  旧モデル (schema 0.11 以前) はロード時に自動で等価変換されます

制約 (v0.56.0 時点): 連続ブロック (Integrator 等) の入力は float64 に自動昇格 /
Subsystem・PythonFunction 境界は float64 / 状態持ちブロックの内部状態は
float64 保持 / 非 float64 モデルは `linearize` 等の解析 API で明示拒否。

## バージョニング

[ZeroVer](https://0ver.org/) を採用しており `0.x` に留まり続けます。
**minor** は機能追加または破壊的変更、**patch** は修正。リリースノートは
`CHANGELOG.md` を参照してください。

## 開発

```bash
pytest -ra                                  # テスト
ruff check flode tests examples             # lint (CI と同一対象)
ruff format --check flode tests examples    # format チェック
mypy flode                                  # 型チェック
sphinx-build -W -b html docs docs/_build    # ドキュメント (CI は warning を error 扱い)
```

frontend の開発手順は `flode/web/frontend/README.md` を参照してください。

## ライセンス

MIT — `LICENSE` を参照。
