# flode

[![CI](https://github.com/aramoto99/flode/actions/workflows/ci.yml/badge.svg)](https://github.com/aramoto99/flode/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

# ブロック線図ベースの動的システムシミュレータ

## インストール

前提: **Python 3.11+**。ソースから入れる場合は **Node.js 20+** も必要。

```bash
git clone https://github.com/aramoto99/flode.git
cd flode

# frontend をビルド (flode/server/static/ に出力される)
cd flode/web/frontend && npm install && npm run build && cd ../../..

pip install -e .
```

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