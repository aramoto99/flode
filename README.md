# flode

[![CI](https://github.com/aramoto99/flode/actions/workflows/ci.yml/badge.svg)](https://github.com/aramoto99/flode/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

ブロック線図ベースの動的システムシミュレータ。ブラウザ上でブロックを配線し、
連続系・離散系・その混在系を `scipy.solve_ivp` (既定 RK45) でシミュレートする。

- Web エディタ (配線 / Inspector / ライブプロット)、50+ の組み込みブロック、Subsystem による階層化
- `@block` デコレータで Python 関数をカスタムブロック化
- 解析機能 (線形化、Bode / Nyquist、安定判別、根軌跡)
- モデルはプレーン JSON (`.flw.json`)

## インストール

前提: **Python 3.11+**。ソースから入れる場合は **Node.js 20+** も必要。

```bash
git clone https://github.com/aramoto99/flode.git
cd flode

# frontend をビルド (flode/server/static/ に出力される)
cd flode/web/frontend && npm install && npm run build && cd ../../..

pip install -e .
```

[GitHub Releases](https://github.com/aramoto99/flode/releases) の prebuilt wheel なら Node 不要。PyPI 未公開のため `pip install flode` は不可。

## 使い方

### Web GUI

```bash
flode                                       # サーバ起動 + ブラウザが自動で開く
flode --workspace ./my-models --port 8770   # workspace とポートを指定
flode --no-browser                          # ブラウザを開かない
```

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

## 時間のモデル (v0.58〜)

時間の刻みは 3 層に分離されている:

| | 正体 | 誰のものか |
|---|---|---|
| 積分ステップ | ソルバ内部の適応刻み (rtol/atol が制御) | 計算機構 (自動) |
| `sample_time` | 離散ブロックの周期 | 系 (モデルの仕様) |
| `dt` | イベント発火・記録の基準サンプル周期 | シミュレーション設定 |

離散ブロックの `sample_time` は 3 通りで指定する:

- **指定** (`0.2` 等) — 固有のクロックを持つ装置。dt を変えても追従しない
- **継承** (`-1`) — 上流のブロックから周期を継承。継承できる周期が上流になければエラー (案内付き)
- **基準クロック** (`"dt"`) — シミュレーションの dt に同期。観測・実験用の器具ブロック向け

`dt` は積分刻みではない (連続系の精度は許容誤差 rtol/atol が決める)。
Subsystem 内部の離散ブロックは明示周期のみ対応。

## 信号の dtype (v0.55〜)

`Cast` / `Constant` の `dtype` param (`float64` / `int32` / `int64` / `uint8` / `bool`) を
宣言すると、下流の信号が実際にその型で計算される (numpy ネイティブ意味論:
整数オーバーフローは wrap、`bool + bool` は論理和)。未宣言のモデルは全経路
float64 で bit 単位に従来どおり。偶数丸めは `Rounding(mode="round")`、0/1 化は
`CompareToZero(op="!=")` を使う。旧 schema のモデルはロード時に自動 migration。

制約: 連続ブロック入力は float64 に自動昇格 / Subsystem・PythonFunction 境界は
float64 / 非 float64 モデルは `linearize` 等の解析 API で明示拒否。

## PythonFunction の注意

`PythonFunction` ブロックはユーザー Python コードを実行する。モデルを開くだけでは
実行されず、初回実行前に確認ダイアログが出る。`127.0.0.1` 以外に bind した
サーバでは `flode --allow-python-blocks` なしに実行不可。式で書けるロジックには
`Fcn` を使う。

## バージョニング

[ZeroVer](https://0ver.org/) を採用 (`0.x` に留まる)。minor = 機能追加・破壊的変更、
patch = 修正。

## ライセンス

MIT
