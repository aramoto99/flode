# pyflw

A block-diagram dynamic system simulator for Python, inspired by Simulink. Build
continuous, discrete, and hybrid models by wiring pre-built blocks, then integrate
with `scipy.solve_ivp` (default: RK45).

## Requirements

- Python 3.10+
- numpy, scipy, matplotlib (installed automatically)

## Installation

```bash
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

| Category   | Blocks                                                     |
|------------|------------------------------------------------------------|
| Sources    | Constant, Step, Sine, Ramp, Clock, PulseGenerator         |
| Sinks      | Scope, Terminator                                          |
| Continuous | Integrator                                                 |
| Discrete   | UnitDelay, DiscreteIntegrator, ZeroOrderHold               |
| Math       | Gain, Sum, Product, Saturation, Abs, Sign, MinMax, Divide  |
| Logic      | RelationalOperator, LogicalOperator                        |
| Routing    | Switch                                                     |

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

Class-form (`@block` applied to a class) is planned for Phase 2.

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
  core/       Block base class, Simulator, @block decorator
  blocks/     Block implementations (sources, sinks, continuous, discrete, …)
examples/     Runnable scripts (e.g. spring_mass_damper.py)
tests/        pytest test suite
docs/         Sphinx source
```
