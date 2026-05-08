# pyflw

A block-diagram dynamic system simulator for Python, inspired by Simulink. Build
continuous, discrete, and hybrid models by wiring pre-built blocks, then integrate
with `scipy.solve_ivp` (default: RK45).

**Stable as of v0.13.0** (2026-05-09, ADR-0038). Public API + JSON schema + REST
`/api/v1/*` + extras names (`pyflw[gui/control/codegen/gpu]`) are frozen under
SemVer; subsequent breaking changes require v2.0.

## Requirements

- Python 3.11+
- numpy >= 2.3, scipy >= 1.10, matplotlib >= 3.7 (installed automatically)

## Installation

```bash
# Core only
pip install -e .

# With Web GUI (FastAPI server + bundled React frontend)
pip install -e ".[gui]"

# Analysis (linearize + control extras for Bode/Nyquist/root locus)
pip install -e ".[control]"

# jax-first Codegen + Autodiff (CPU only; required for Simulator.compile()
# and linearize(method="jax"))
pip install -e ".[codegen]"

# GPU backend (NVIDIA CUDA 12, Linux x86_64 wheel only). Real-machine
# benchmarks are Phase 6+; SPEC-0001 §non-functional treats GPU as
# best-effort.
pip install -e ".[gpu]"

# Development environment (pytest, ruff, mypy, sphinx, server tooling)
pip install -e ".[dev]"
```

PyPI package is not yet published; install from source only.

## Quick Example

```python
from pyflw import Simulator
from pyflw.blocks import Constant, Gain, Integrator, Scope

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

| Category   | Blocks                                                                    |
|------------|---------------------------------------------------------------------------|
| Sources    | Constant, Step, Sine, Ramp, Clock, PulseGenerator                        |
| Sinks      | Scope, Terminator, Display, XYGraph                                       |
| Continuous | Integrator, StateSpace, TransferFunction, MimoTransferFunction, Derivative |
| Discrete   | UnitDelay, DiscreteIntegrator, ZeroOrderHoldDirect, DiscreteStateSpace, DiscreteTransferFunction, RateTransition |
| Math       | Gain, Sum, Product, Saturation, Abs, Sign, MinMax, Divide                 |
| Logic      | RelationalOperator, LogicalOperator                                       |
| Routing    | Switch, Mux, Demux                                                        |
| Subsystem  | Subsystem, TriggeredSubsystem, Inport, Outport                            |

Full API reference: `docs/` (build with `sphinx-build -b html docs docs/_build`).

## `@block` Decorator

Turn a plain function into a `Block` subclass without subclassing `Block` directly:

```python
import numpy as np
from pyflw import block

@block(states=1)
def my_integrator(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
    y = x[0]
    x_dot = np.array([u])
    return y, x_dot
```

Class-form (`@block` applied to a class) is also supported (ADR-0003 §(9)) for
blocks that prefer separate `output` / `derivative` / `update` methods.

## Codegen + Autodiff (jax-first, opt-in)

`Simulator.compile(backend="jax")` and `linearize(method="jax")` (ADR-0037,
v0.17.0) trace selected blocks through `jax.jit` / `jax.jacfwd` for XLA
compilation and machine-precision Jacobians. The numpy hot path is unchanged
unless `compile()` is called (= `examples/spring_mass_damper.py` numerics
remain bit-identical to v0.1.0).

```python
from pyflw import Simulator, linearize
from pyflw.blocks import Constant, Sum, Gain, Integrator

sim = Simulator(t_end=10.0, dt=0.01)
src   = sim.add(Constant(value=1.0))
err   = sim.add(Sum(signs="+-"))
gain  = sim.add(Gain(k=2.0))
integ = sim.add(Integrator())
sim.connect(src, (err, 0))
sim.connect(integ, (err, 1))
sim.connect(err, gain)
sim.connect(gain, integ)

# jax.jacfwd で機械精度 (atol=1e-12) の (A, B, C, D) を取得
ls = linearize(sim, method="jax")
print(ls.A.shape, ls.eigenvalues())

# CompiledSimulator (Phase 6+ で run() 本格実装予定)
compiled = sim.compile(backend="jax")
print(compiled.n_states, compiled.backend)
```

`pyflw[codegen]` extras (`jax[cpu]`) を要求。GPU は `pyflw[gpu]` extras
(`jax[cuda12]`、Linux x86_64 / NVIDIA CUDA 12 only)、実機ベンチマークは Phase
6+ で整備予定。`Simulator.compile()` で未対応ブロック (= `StateSpace` /
`TransferFunction` / `Subsystem` / `TriggeredSubsystem` 等) を含むモデルは
`BlockSpecError` で拒否される。詳細: ADR-0037 / ADR-0038。

## Web GUI (Phase 2)

After installing the `gui` extras, launch the FastAPI server:

```bash
pyflw-server --model-dir ./models --port 8770
```

Then open `http://127.0.0.1:8770` in a browser. Models are read from and
written to `--model-dir` as `.flw.json` files (ADR-0008). The browser UI gives
you a model list, a read-only diagram view (React Flow), Run/Stop controls,
and a live scope plot fed by WebSocket. Drag-and-drop editing and parameter
inline editing are slated for Phase 3 (see ADR-0012 §(10)).

Frontend development (Vite dev server) is documented in
`pyflw/web/frontend/README.md`.

Note: the bundled web GUI ships only with **wheel** artifacts produced by the
release CI (which runs `npm run build` before `python -m build`). If you
install pyflw from an **sdist** (or from a fresh `pip install -e .` without
running `npm run build`), `pyflw/server/static/` is empty and the browser
will show 404 at `/`. The REST/WebSocket API at `/api/v1/*` still works.

## Development

```bash
# Run tests
pytest -ra

# Lint
ruff check pyflw tests

# Type-check
mypy pyflw

# Build HTML docs
sphinx-build -b html docs docs/_build
```

## Directory Layout

```
pyflw/
  core/       Block base class, Simulator, @block decorator, JSON persistence
  blocks/     Block implementations (sources, sinks, continuous, discrete, ...)
  subsystems/ Atomic Subsystem and Inport / Outport (ADR-0009)
  server/     Optional FastAPI Web GUI backend (pyflw[gui])
  web/
    frontend/ Vite + React + TypeScript GUI source (built into server/static)
examples/     Runnable scripts (e.g. spring_mass_damper.py)
tests/        pytest test suite
docs/         Sphinx source
.claude/      Internal design documents (SPECs, ADRs)
```

## License

MIT — see `LICENSE`.
