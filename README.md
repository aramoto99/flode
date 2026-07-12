# pyflw

A block-diagram dynamic system simulator for Python. Build continuous, discrete,
and hybrid models by wiring pre-built blocks, then integrate with
`scipy.solve_ivp` (default: RK45).

**Current: v0.41.0** (2026-07-11). pyflw follows
[ZeroVer](https://0ver.org/) (永久 0.x) — within `0.x`, a **minor** bump is a
feature or breaking change and a **patch** bump is a fix. The public Python API,
`.flw.json` JSON schema (now **0.9**), REST `/api/v1/*` surface, and extras
names (`pyflw[gui/control/codegen/gpu]`) are kept stable across patch releases;
breaking changes are called out in `CHANGELOG.md` and bump the minor.

Recent highlights on top of the v2 core:

- **One-command startup UX** (v0.41.0, SPEC-0021) — `pyflw` opens
  your default browser automatically and falls back to the next free port when
  the requested one is busy (`--no-browser` / `[server] port_retries = 0` to
  opt out).
- **Standard block library expansion** (v0.39.0, ADR-0059) — 15 new blocks:
  N-D lookup tables, arbitrary-expression `Fcn`, noise sources, discontinuity
  elements (Relay / RateLimiter), multiport routing (Goto / From / Merge /
  MultiportSwitch), transport delay, and more.
- **IDE-style workspace** — local file direct editing (ADR-0041),
  multi-tab editor + Recent Files + fuzzy search (ADR-0043), and staged
  workspace convergence (multi-pane / activity bar / drag-to-split,
  ADR-0045 / 0051 / 0052).
- **Open-ended runs** — Stop Time = `inf` with a ring-buffer scope (ADR-0042).
- **Scope UX** — per-scope plot settings + floating scope windows (ADR-0044).
- **Subsystem behavior modifiers** — Trigger / Enable as in-subsystem control
  blocks (ADR-0058); the standalone `TriggeredSubsystem` class was removed in
  v0.38.0.
- **Property-Inspector-style UI design system** across every settings dialog.

## Requirements

- Python 3.11+
- numpy >= 2.3, scipy >= 1.10, matplotlib >= 3.7 (installed automatically)

## Installation

pyflw is distributed via `git clone` from GitHub (no PyPI package).

### Prerequisites

- **Python 3.11+** — required for the core simulator.
- **Node.js 20+ and npm** — required *only* if you want the Web GUI
  (= the `[gui]` extras). The React frontend is not committed to git, so
  you build it once locally with `npm run build` before installing the
  `[gui]` extras. Skip Node entirely if you only need the Python API.

### Core only (Python API)

```bash
git clone https://github.com/aramoto99/pyflw.git
cd pyflw
pip install -e .
```

### Web GUI

The Web GUI frontend (`pyflw/server/static/`) is a build artifact and is
not committed to git. Build it once before installing the `[gui]` extras:

```bash
git clone https://github.com/aramoto99/pyflw.git
cd pyflw

# Build the React frontend → outputs into pyflw/server/static/ via
# pyflw/web/frontend/scripts/deploy-to-server-static.mjs
cd pyflw/web/frontend
npm install
npm run build
cd ../../..

# Install the Python side (FastAPI server + bundled static)
pip install -e ".[gui]"

# Start the server — opens your default browser automatically (SPEC-0021).
# If port 8770 is busy it falls back to 8771, 8772, ... (up to 50 tries).
# (`pyflw-server` also works as a compatibility alias.)
pyflw

# Options: custom workspace/port, headless (no browser)
pyflw --workspace ./workspace --port 8770
pyflw --no-browser
# Fixed-port setups (reverse proxy etc.): set `[server] port_retries = 0`
# in ~/.pyflw/config.toml to fail immediately instead of falling back.
# `pyflw --generate-config` writes a commented template with all
# keys ([server] open_browser / port_retries etc.).
```

Re-run `npm run build` after any `git pull` that touches
`pyflw/web/frontend/`. If you skip the build step, `pip install -e ".[gui]"`
still succeeds but the browser will show 404 at `/` (the REST/WebSocket
API at `/api/v1/*` keeps working).

### Other extras

```bash
# Analysis (linearize + python-control for Bode/Nyquist/root locus)
pip install -e ".[control]"

# jax-first Codegen + Autodiff (CPU only; for Simulator.compile()
# and linearize(method="jax"))
pip install -e ".[codegen]"

# GPU backend (NVIDIA CUDA 12, Linux x86_64 wheel only; best-effort,
# real-machine benchmarks are Phase 6+, SPEC-0001 §non-functional)
pip install -e ".[gpu]"

# Development environment (pytest, ruff, mypy, sphinx, server tooling)
pip install -e ".[dev]"
```

Multiple extras can be combined: `pip install -e ".[gui,control,dev]"`.

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
| User Function   | Fcn (AST-whitelisted arbitrary expression `y = f(t, u)`)                  |
| Subsystem       | Subsystem (Trigger / Enable control block で挙動修飾、ADR-0058)            |
| Control         | Inport, Outport, Trigger, Enable                                          |

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
`TransferFunction` / `Subsystem` 等) を含むモデルは
`BlockSpecError` で拒否される。詳細: ADR-0037 / ADR-0038。

## Web GUI

After installing the `gui` extras, launch the FastAPI server with a workspace
root (= directory containing your `.flw.json` files, ADR-0041):

```bash
pyflw --workspace ./workspace --port 8770
```

Your default browser opens the UI automatically (SPEC-0021; `--no-browser`
to disable). `pyflw-server` still works as a compatibility alias.

### Persisting server defaults (`~/.pyflw/config.toml`)

If you find yourself typing the same `--workspace` / `--port` / `--allow-origin`
every time, persist them in `~/.pyflw/config.toml` (SPEC-0004). Generate a
commented template with:

```bash
pyflw --generate-config
```

The template lives at `~/.pyflw/config.toml` (or `%USERPROFILE%\.pyflw\config.toml`
on Windows). Edit it, then just run `pyflw` with no arguments:

```toml
[server]
host = "127.0.0.1"
port = 8770

[settings]
workspace = "~/pyflw-workspace"
scope_batch_size = 100
max_concurrent = 4
allow_origins = []
library_paths = []
bundle_builtin_libraries = true
```

Priority is **CLI args > config file > defaults** — pass `--port 9000` on the
command line to override the file for a single run. Use `--config=PATH` to
load a non-default file (handy for per-project setups), or omit the file
entirely to fall back to defaults (= `workspace` becomes the current working
directory).

### What the browser UI gives you

- **IDE-style file tree** (subdirectories, rename / new / delete via
  context menu, drag-and-drop reorder, ADR-0041 / ADR-0043).
- **Multi-tab editor** with dirty indicator (`●`) + "Save all" + close-other
  tabs, last-active tab restored across reload per workspace (ADR-0043).
- **Recent Files** — most-recently-opened list scoped per workspace
  (`localStorage`, top 20, ADR-0043).
- **Fuzzy search** — `Ctrl+P` for path search (rapidfuzz `WRatio`),
  `Ctrl+Shift+F` for content search across `.flw.json`. Hits jump straight
  to the file in the editor.
- **Block library** with category accordions + drag-and-drop onto the canvas.
- **Auto-connect on edge drop** — drop a SISO block onto an existing edge
  to splice it in place (= source → block → target, ADR-0044).
- **Inspector panel** — Property Inspector-style parameter editor
  for the selected block, with collapse-to-widen-canvas affordance.
- **Workspace ↔ Library ↔ Canvas ↔ Scope split** — every divider is
  drag-resizable, sizes persisted in localStorage.
- **Run / Stop / Stop Time** controls. Stop Time = `inf` switches the
  simulator into an open-ended `while True` loop with a ring buffer scope
  (default `MAX_SAMPLES = 100_000`, ADR-0042).
- **Scope** — live plots streamed over WebSocket. Each Scope block has a
  gear icon for per-scope plot settings (Y/X axis auto/manual/log, legend
  position, grid, per-signal line color & width — saved in `.flw.json`
  under `scope_settings`, ADR-0044).
- **Floating Scope** — double-click a Scope block to pop its plot into a
  draggable / resizable floating window (`react-rnd`). Multiple scopes can
  float simultaneously; positions persist in localStorage; switching models
  closes all open scopes (ADR-0044).

All file operations go through `/api/v1/files/*` (= contents-style REST
API). The model itself is just JSON in your workspace — open it in any
editor and the changes appear in the UI on next focus (external-changes poll).

### Migration from v2.x

If you previously ran pyflw with the legacy `--model-dir DIR` (= v2.x),
migrate the flat layout to a workspace once with:

```bash
pyflw --migrate-models-to=./workspace --legacy-models-dir=./old_models
```

then start with `--workspace=./workspace`. The migration command is provided
for one release only.

### Notes

- Frontend development (Vite dev server with hot reload) is documented in
  `pyflw/web/frontend/README.md`.
- `pyflw/server/static/` is a build output, not source — it is generated by
  `npm run build` in `pyflw/web/frontend/` and is excluded from git. See
  the [Web GUI installation](#web-gui) section for the build step.
- The `/api/v1/files/search` endpoint hard-excludes well-known credential
  paths (`.env*`, `id_rsa`, `id_ed25519`, `.ssh/`, `.aws/`, `.gnupg/`,
  `.docker/`, `.idea/`) regardless of workspace contents (= cannot return
  bytes that could leak secrets, v0.26.11).

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
  blocks/     Block implementations (sources, mathops, continuous, discrete,
              logic, routing, sinks, lookup, discontinuities, ...)
  subsystems/ Subsystem, Triggered/Enable behavior, ports, mask (ADR-0009 / 0058)
  analysis/   linearize / frequency_response / stability (ADR-0026 / 0027)
  compile/    compiled_simulator / jax_backend codegen (ADR-0037, pyflw[codegen])
  libraries/  Block library loader + std.flwlib.json (ADR-0029)
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
