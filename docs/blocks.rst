Block Library
=============

All blocks are importable from ``pyflw.blocks``.

.. code-block:: python

   from pyflw.blocks import Constant, Gain, Integrator, Scope

Sources
-------

Blocks with no inputs that generate signal values as a function of time.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.Constant
   pyflw.blocks.Step
   pyflw.blocks.Sine
   pyflw.blocks.Ramp
   pyflw.blocks.Clock
   pyflw.blocks.PulseGenerator

Sinks
-----

Blocks that consume signals without producing outputs.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.Scope
   pyflw.blocks.Terminator

Continuous
----------

Blocks with continuous-time state integrated by ``scipy.solve_ivp``.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.Integrator

Discrete
--------

Blocks updated at a fixed sample period. Pass ``sample_time`` in seconds.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.UnitDelay
   pyflw.blocks.DiscreteIntegrator
   pyflw.blocks.ZeroOrderHold

.. note::

   ``ZeroOrderHold`` in Phase 1 holds the *previous* sample (equivalent to
   ``UnitDelay``). A ``direct_feedthrough=True`` variant is planned for
   Phase 2.

Math
----

Combinational arithmetic blocks (``direct_feedthrough=True``).

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.Gain
   pyflw.blocks.Sum
   pyflw.blocks.Product
   pyflw.blocks.Saturation
   pyflw.blocks.Abs
   pyflw.blocks.Sign
   pyflw.blocks.MinMax
   pyflw.blocks.Divide

Logic
-----

Relational and logical operators. Logical values are represented as ``0.0``
(false) and ``1.0`` (true) on float signals.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.RelationalOperator
   pyflw.blocks.LogicalOperator

Routing
-------

Signal selection and routing blocks.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   pyflw.blocks.Switch
