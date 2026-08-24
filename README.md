# flode

[![CI](https://github.com/aramoto99/flode/actions/workflows/ci.yml/badge.svg)](https://github.com/aramoto99/flode/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**flode** (**FLO**w + o**DE**) is a block-diagram dynamic system simulator: build a
model visually in your browser by wiring together blocks, then simulate it —
continuous, discrete, or a mix of both — on top of `scipy.solve_ivp`.

## Features

- **Web-based diagram editor** — drag blocks onto a canvas, wire them up, edit
  parameters in an inspector panel, and run the simulation with live-streaming
  plots, all in the browser. No separate app to install.
- **50+ built-in blocks** covering sources, sinks, continuous/discrete dynamics,
  math, logic, lookup tables, routing, and discontinuities (see
  [Block Library](#block-library)).
- **Continuous, discrete, and hybrid simulation** via `scipy.solve_ivp`
  (default solver: RK45), with automatic detection of algebraic loops.
- **Subsystems** for hierarchical models, with in-subsystem Trigger / Enable
  blocks to control when a subsystem executes.
- **Custom blocks in a few lines of Python** via the `@block` decorator — no
  need to subclass anything.
- **Analysis tools** — numerical linearization, Bode/Nyquist frequency
  response, eigenvalue-based stability, and root locus.
- **Optional GPU/autodiff backend** (JAX) for machine-precision Jacobians and
  compiled simulation, opt-in via extras.
- **Plain JSON models** (`.flw.json`) — version-control friendly, editable by
  hand or by any tool.

## Installation

### Prerequisites

- **Python 3.11+**
- **Node.js 20+ and npm** — only needed for a source install (the Web GUI's
  frontend is not committed to git, so you build it once locally). Prebuilt
  wheels attached to [GitHub Releases](https://github.com/aramoto99/flode/releases)
  already contain the built frontend and need no Node.

### Install from source

```bash
git clone https://github.com/aramoto99/flode.git
cd flode

# Build the frontend once (outputs into flode/server/static/)
cd flode/web/frontend
npm install
npm run build
cd ../../..

# Install the package (core simulator + server + bundled frontend)
pip install -e .
```

Re-run `npm run build` after any `git pull` that touches
`flode/web/frontend/`. Skipping the build step still lets `pip install -e .`
succeed, but the browser will show a 404 at `/` (the REST/WebSocket API under
`/api/v1/*` keeps working regardless).

### Install a prebuilt wheel (no Node.js required)

Download the `.whl` file from the
[latest GitHub Release](https://github.com/aramoto99/flode/releases/latest)
and install it directly:

```bash
pip install flode-<version>-py3-none-any.whl
```

flode is not yet published on PyPI, so `pip install flode` does not work today.

### Optional extras

```bash
# Analysis extras: python-control-backed Bode/Nyquist/root locus
pip install -e ".[control]"

# JAX-based codegen + autodiff (CPU): Simulator.compile() and linearize(method="jax")
pip install -e ".[codegen]"

# GPU backend (NVIDIA CUDA 12, Linux x86_64 only, best-effort)
pip install -e ".[gpu]"

# Development environment (pytest, ruff, mypy, sphinx)
pip install -e ".[dev]"
```

Extras can be combined, e.g. `pip install -e ".[control,dev]"`.

## Getting Started

### Web GUI

```bash
flode
```

This starts the local server and opens the UI in your default browser
automatically. If the requested port is busy it falls back to the next free
one. Useful flags:

```bash
flode --workspace ./my-models --port 8770   # custom workspace + port
flode --no-browser                          # headless (CI, background use)
```

A workspace is just a directory of `.flw.json` files — open the file tree in
the sidebar, drag a block from the library onto the canvas, wire it up in the
inspector panel, and hit Run to see live plots in the Scope panel.

The server binds to `127.0.0.1` by default, and the workspace search API
always excludes well-known credential paths (`.env*`, `id_rsa`, `.ssh/`,
`.aws/`, ...) regardless of workspace contents, so search results cannot leak
secrets.

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

See `examples/spring_mass_damper.py` for a complete second-order system example.

## Block Library

| Category        | Blocks                                                                    |
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
| User Function   | Fcn (arbitrary `y = f(t, u)` expression, AST-whitelisted for safety)     |
| Subsystem       | Subsystem (behavior modified via inner Trigger / Enable control blocks)  |
| Control         | Inport, Outport, Trigger, Enable                                          |

Most blocks are importable directly from `flode.blocks`; a few GUI-oriented
variants (e.g. `Add`) live in their submodule (`flode.blocks.mathops.Add`).

For the full API reference, build the docs locally:
`sphinx-build -b html docs docs/_build`.

## `@block` Decorator

Turn a plain function into a `Block` subclass without subclassing `Block` directly:

```python
import numpy as np
from flode import block

@block(states=1)
def my_integrator(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
    y = x[0]
    x_dot = np.array([u])
    return y, x_dot
```

A class-based form (`@block` applied to a class) is also supported for blocks
that prefer separate `output` / `derivative` / `update` methods.

## Analysis

`flode.linearize()` numerically linearizes a model around an operating point
`(t, x, u)` and returns a `LinearSystem` with state-space matrices `(A, B, C, D)`:

```python
from flode import linearize

ls = linearize(sim)
print(ls.A.shape, ls.eigenvalues(), ls.is_stable())
```

`bode()`, `nyquist()`, and `root_locus()` build on `LinearSystem` and require
the `flode[control]` extras (`python-control`); `eigenvalues()` / `is_stable()`
work with numpy alone.

## Codegen + Autodiff (JAX, opt-in)

`Simulator.compile(backend="jax")` and `linearize(method="jax")` trace
selected blocks through `jax.jit` / `jax.jacfwd` for XLA compilation and
machine-precision Jacobians. The default numpy execution path is unaffected
unless `compile()` is explicitly called.

```python
from flode import Simulator, linearize

sim = Simulator(t_end=10.0, dt=0.01)
# ... build model ...

# machine-precision (A, B, C, D) via jax.jacfwd
ls = linearize(sim, method="jax")

compiled = sim.compile(backend="jax")
print(compiled.n_states, compiled.backend)
```

Requires the `flode[codegen]` extras (`jax[cpu]`). The GPU backend uses
`flode[gpu]` (`jax[cuda12]`, Linux x86_64 with NVIDIA CUDA 12 only).

Note that the JAX backend is still experimental and supports only a small
subset of blocks so far (`Constant`, `Step`, `Sine`, `Ramp`, `Clock`, `Gain`,
`Sum`, `Integrator`, plus sinks); models containing any other block are
rejected with `BlockSpecError`.

## Configuration

Persist server defaults (`--workspace`, `--port`, `--allow-origin`, ...) in
`~/.flode/config.toml` (`%USERPROFILE%\.flode\config.toml` on Windows) so you
don't have to pass them every time. Generate a commented template with:

```bash
flode --generate-config
```

```toml
[server]
host = "127.0.0.1"
port = 8770

[settings]
workspace = "~/flode-workspace"
scope_batch_size = 100
max_concurrent = 4
allow_origins = []
library_paths = []
bundle_builtin_libraries = true
```

Priority is **CLI args > config file > defaults** — e.g. `--port 9000` on the
command line overrides the file for a single run. Use `--config=PATH` to load
a non-default file, or omit the config file entirely to fall back to defaults
(workspace defaults to the current working directory).

If you are upgrading from a very old version that used the flat `--model-dir`
layout, migrate it once with
`flode --migrate-models-to=./workspace --legacy-models-dir=./old_models`
(deprecated; will be removed in a future release).

## Versioning

flode follows [ZeroVer](https://0ver.org/): it stays on `0.x` indefinitely.
Within `0.x`, a **minor** bump is a feature or breaking change and a **patch**
bump is a fix. See `CHANGELOG.md` for release notes (single source of truth:
`flode.__version__`).

## Development

```bash
# Run tests
pytest -ra

# Lint + format check (same targets as CI)
ruff check flode tests examples
ruff format --check flode tests examples

# Type-check
mypy flode

# Build HTML docs (CI treats warnings as errors)
sphinx-build -W -b html docs docs/_build
```

Frontend development (Vite dev server with hot reload) is documented in
`flode/web/frontend/README.md`.

## Directory Layout

```
flode/
  core/       Block base class, Simulator, @block decorator, JSON persistence
  blocks/     Block implementations (sources, mathops, continuous, discrete,
              logic, routing, sinks, lookup, discontinuities, ...)
  subsystems/ Subsystem, Trigger/Enable behavior, ports, mask
  analysis/   linearize / frequency_response / stability
  compile/    compiled_simulator / jax_backend codegen (flode[codegen])
  libraries/  Block library loader + std.flwlib.json
  server/     FastAPI Web GUI backend
  web/
    frontend/ Vite + React + TypeScript GUI source (built into server/static)
examples/     Runnable scripts (e.g. spring_mass_damper.py)
tests/        pytest test suite
docs/         Sphinx source
```

## License

MIT — see `LICENSE`.
