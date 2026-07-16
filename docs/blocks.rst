Block Library
=============

All blocks are importable from ``flode.blocks``.

.. code-block:: python

   from flode.blocks import Constant, Gain, Integrator, Scope

Sources
-------

Blocks with no inputs that generate signal values as a function of time.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.Constant
   flode.blocks.Step
   flode.blocks.Sine
   flode.blocks.Ramp
   flode.blocks.Clock
   flode.blocks.PulseGenerator

Sinks
-----

Blocks that consume signals without producing outputs.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.Scope
   flode.blocks.Terminator

Continuous
----------

Blocks with continuous-time state integrated by ``scipy.solve_ivp``.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.Integrator

Discrete
--------

Blocks updated at a fixed sample period. Pass ``sample_time`` in seconds.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.UnitDelay
   flode.blocks.DiscreteIntegrator
   flode.blocks.ZeroOrderHoldDirect

.. note::

   The legacy ``ZeroOrderHold`` block (state-based, equivalent to
   ``UnitDelay`` after ADR-0014) was deprecated in v0.5.0 and **removed in
   v0.13.0** (ADR-0033). For 1-sample delayed sample-and-hold use
   :class:`flode.blocks.UnitDelay`; for reference-tool-compatible immediate
   reflection (``y(t_k) = u(t_k)``) use
   :class:`flode.blocks.ZeroOrderHoldDirect` (ADR-0014 §(3)).

Math
----

Combinational arithmetic blocks (``direct_feedthrough=True``).

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.Gain
   flode.blocks.Sum
   flode.blocks.Product
   flode.blocks.Saturation
   flode.blocks.Abs
   flode.blocks.Sign
   flode.blocks.MinMax
   flode.blocks.Divide

Logic
-----

Relational and logical operators. Logical values are represented as ``0.0``
(false) and ``1.0`` (true) on float signals.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.RelationalOperator
   flode.blocks.LogicalOperator

Routing
-------

Signal selection and routing blocks.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.Switch
