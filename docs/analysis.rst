Analysis
========

The :mod:`flode.analysis` package provides numerical analysis tools that
operate on a built :class:`flode.Simulator`. Phase 4 (introduced in
``v0.10.0``) ships :func:`flode.linearize` for linearisation around a
chosen operating point.

Linearisation (ADR-0026)
------------------------

Given a non-linear ``flode`` model, :func:`flode.linearize` computes the
state-space matrices :math:`(A, B, C, D)` of the locally linearised
system around an operating point :math:`(t^*, x^*, u^*)` using a finite
difference (central or forward) of ``Block.derivative`` and ``Block.output``.

The model must contain at least one continuous-time state (e.g.
:class:`flode.blocks.Integrator`, :class:`flode.blocks.StateSpace`,
:class:`flode.blocks.TransferFunction`). Discrete blocks are held at
their initial values during linearisation and a ``UserWarning`` is
emitted; full hybrid linearisation is on the Phase 5+ roadmap.

Quick example
~~~~~~~~~~~~~

.. code-block:: python

   from flode import Simulator, linearize
   from flode.blocks import Integrator, Scope

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

If you install ``flode`` with the ``[control]`` extra
(``pip install flode[control]``), :meth:`LinearSystem.to_control_ss`
returns a ``control.StateSpace`` instance suitable for the rest of the
`python-control <https://python-control.readthedocs.io/>`_ ecosystem:

.. code-block:: python

   import control

   ls = sim.linearize()
   ss = ls.to_control_ss()
   mag, phase, omega = control.frequency_response(ss)

Frequency response and stability (ADR-0027, v0.10.1)
----------------------------------------------------

Built on top of :class:`LinearSystem`, ``v0.10.1`` ships a thin layer
of analysis helpers:

* :func:`flode.bode` — Bode magnitude/phase via ``python-control``
  (``[control]`` extra required).
* :func:`flode.nyquist` — Nyquist locus.
* :func:`flode.eigenvalues` — A-matrix eigenvalues, ``np.linalg.eig``
  thin wrapper. Works **without** the ``[control]`` extra.
* :func:`flode.is_stable` — strict-negative real-part check, also
  numpy-only.
* :func:`flode.root_locus` — SISO root locus (``[control]`` required;
  pass ``input_idx`` / ``output_idx`` to slice a SISO sub-system out
  of a MIMO :class:`LinearSystem`).

Each of these is also available as a method on :class:`LinearSystem`,
following the same delegation pattern as ``Simulator.linearize``.

.. code-block:: python

   import matplotlib.pyplot as plt
   from flode import bode, eigenvalues, is_stable, linearize

   ls = linearize(sim)
   print("Eigenvalues:", eigenvalues(ls))
   print("Stable?", is_stable(ls))

   ax = ls.bode().plot()                   # 2-row Bode plot
   ax_ny = ls.nyquist().plot()             # Nyquist locus
   ax_rl = ls.root_locus().plot()          # SISO root locus

   plt.show()

The result objects (:class:`BodeResponse`, :class:`NyquistResponse`,
:class:`RootLocus`) are frozen dataclasses holding the raw numpy arrays
plus the ``input_names`` / ``output_names`` labels inherited from the
``LinearSystem`` they were derived from. ``magnitude`` / ``phase`` /
``response`` arrays follow ``python-control`` 0.10's MIMO convention
(``(p, m, n_omega)``) — index with ``[output_idx, input_idx, :]`` to
extract a SISO channel.

API reference
-------------

.. automodule:: flode.analysis.linearize
   :members: linearize, LinearSystem
   :show-inheritance:

.. automodule:: flode.analysis.frequency_response
   :members: bode, nyquist, BodeResponse, NyquistResponse
   :show-inheritance:

.. automodule:: flode.analysis.stability
   :members: eigenvalues, is_stable, root_locus, RootLocus
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

The perturbation step ``h`` is selected per dimension as
``sqrt(eps_machine) * max(|x_i|, 1.0)`` by default, balancing
truncation and round-off error. Override with ``epsilon=...``.
