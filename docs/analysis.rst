Analysis
========

The :mod:`pyflw.analysis` package provides numerical analysis tools that
operate on a built :class:`pyflw.Simulator`. Phase 4 (introduced in
``v0.10.0``) ships :func:`pyflw.linearize` for linearisation around a
chosen operating point.

Linearisation (ADR-0026)
------------------------

Given a non-linear ``pyflw`` model, :func:`pyflw.linearize` computes the
state-space matrices :math:`(A, B, C, D)` of the locally linearised
system around an operating point :math:`(t^*, x^*, u^*)` using a finite
difference (central or forward) of ``Block.derivative`` and ``Block.output``.

The model must contain at least one continuous-time state (e.g.
:class:`pyflw.blocks.Integrator`, :class:`pyflw.blocks.StateSpace`,
:class:`pyflw.blocks.TransferFunction`). Discrete blocks are held at
their initial values during linearisation and a ``UserWarning`` is
emitted; full hybrid linearisation is on the Phase 5+ roadmap.

Quick example
~~~~~~~~~~~~~

.. code-block:: python

   from pyflw import Simulator, linearize
   from pyflw.blocks import Integrator, Scope

   sim = Simulator(t_end=10.0, dt=0.01)
   integrator = sim.add(Integrator())
   sim.connect(integrator, sim.add(Scope()))

   ls = linearize(sim)
   print(ls.A)  # [[0.]]   integrator pole at the origin
   print(ls.B)  # [[1.]]   external input couples 1:1 to xdot
   print(ls.C)  # [[1.]]   the only "external" output is x
   print(ls.D)  # [[0.]]
   print(ls.state_names)   # ['Integrator_0.x[0]']
   print(ls.input_names)   # ['Integrator_0.in[0][0]']
   print(ls.output_names)  # ['Integrator_0.out[0][0]']

Connecting to ``python-control``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you install ``pyflw`` with the ``[control]`` extra
(``pip install pyflw[control]``), :meth:`LinearSystem.to_control_ss`
returns a ``control.StateSpace`` instance suitable for Bode plots,
Nyquist analysis, eigenvalue computation, and the rest of the
`python-control <https://python-control.readthedocs.io/>`_ ecosystem:

.. code-block:: python

   import control

   ls = sim.linearize()
   ss = ls.to_control_ss()
   mag, phase, omega = control.frequency_response(ss)

API reference
-------------

.. automodule:: pyflw.analysis.linearize
   :members: linearize, LinearSystem
   :show-inheritance:

Operating-point convention
--------------------------

* ``x = None`` (default): each continuous block contributes its ``x0``
  value, concatenated in registration order.
* ``u = None`` (default): zero vector. The dimension equals the number
  of unconnected, non-sink input ports across the model (each SM-B
  vector port is flattened C-order).
* ``t = 0.0`` (default).

External outputs are the union of: (a) output ports that drive at
least one sink (``Scope``, ``Display``, ``XYGraph`` — i.e., a block
with ``n_outputs == 0`` *and* a ``record(t, u)`` method); (b) output
ports with no consumer at all. Pure internal signals (only consumed
by non-sink blocks) are excluded. Note that ``Terminator`` does
**not** count as a sink for this purpose because it has no
``record`` method — connect to ``Scope`` (or ``Display`` /
``XYGraph``) when you need a port exposed in the linearisation
output vector.

Numerical method
----------------

* ``method="central"`` (default): central difference, error ``O(h^2)``.
  Requires ``2n + 1`` evaluations where ``n`` is the input + state
  dimension.
* ``method="forward"``: forward difference, error ``O(h)``. ``n + 1``
  evaluations, half the cost of central. Useful for very large models
  where the precision difference is acceptable.
* ``method="jax"``: reserved for Phase 5+ (autodifferentiation via
  ``jax``). Calling now raises :class:`NotImplementedError`.

The perturbation step ``h`` is selected per dimension as
``sqrt(eps_machine) * max(|x_i|, 1.0)`` by default, balancing
truncation and round-off error. Override with ``epsilon=...``.
