Quickstart
==========

This guide walks through building a second-order spring-mass-damper model —
the canonical example in ``examples/spring_mass_damper.py``.

The equation of motion is:

.. math::

   m\ddot{x} + c\dot{x} + kx = F

Rearranged for integration:

.. math::

   \ddot{x} = \frac{F - c\dot{x} - kx}{m}

Step 1: Create a Simulator
--------------------------

``Simulator`` owns all blocks and drives the integration loop.

.. code-block:: python

   from flode import Simulator

   sim = Simulator(t_end=20.0, dt=0.01)

``t_end`` sets the simulation end time [s]. ``dt`` is the base time step used
for continuous integration via ``scipy.solve_ivp`` (method ``"RK45"`` by
default).

Step 2: Instantiate and register blocks
----------------------------------------

Each block is created separately, then registered with ``sim.add()``.
``add()`` returns the same block object and optionally auto-assigns an ``id``
if none is provided.

.. code-block:: python

   from flode.blocks import Gain, Integrator, Scope, Step, Sum

   m, c, k = 1.0, 0.5, 4.0

   F        = sim.add(Step(step_time=0.0, final_value=1.0, id="F"))
   sum_blk  = sim.add(Sum(signs="+--", id="sum"))
   inv_m    = sim.add(Gain(k=1.0 / m, id="inv_m"))
   i_xd     = sim.add(Integrator(x0=0.0, id="x_dot"))
   i_x      = sim.add(Integrator(x0=0.0, id="x"))
   gain_c   = sim.add(Gain(k=c, id="c"))
   gain_k   = sim.add(Gain(k=k, id="k"))
   scope    = sim.add(Scope(n_inputs=2, labels=["x", "x_dot"], id="response"))

Step 3: Connect blocks
----------------------

``sim.connect(src, dst)`` wires output port 0 of ``src`` to input port 0 of
``dst``. Use ``src_idx`` / ``dst_idx`` to address specific ports.

.. code-block:: python

   sim.connect(F,      sum_blk, dst_idx=0)
   sim.connect(gain_c, sum_blk, dst_idx=1)
   sim.connect(gain_k, sum_blk, dst_idx=2)
   sim.connect(sum_blk, inv_m)
   sim.connect(inv_m,   i_xd)
   sim.connect(i_xd,    i_x)
   sim.connect(i_xd,    gain_c)
   sim.connect(i_x,     gain_k)
   sim.connect(i_x,     scope, dst_idx=0)
   sim.connect(i_xd,    scope, dst_idx=1)

``Integrator`` has ``direct_feedthrough=False``, so feedback through the
integrators does not create an algebraic loop.

Step 4: Run the simulation
--------------------------

``sim.run()`` performs topological sorting, resolves sample times, and drives
the integration loop.

.. code-block:: python

   sim.run()

If an algebraic loop is detected, ``AlgebraicLoopError`` is raised before
integration starts.

Step 5: Inspect and plot results
---------------------------------

``Scope`` accumulates ``(t, u)`` pairs during ``run()``.
Call ``scope.plot()`` after ``run()`` completes.

.. code-block:: python

   scope.plot(show=True)

``scope.values`` gives a ``numpy.ndarray`` of shape ``(n_samples, n_inputs)``
for post-processing.

.. code-block:: python

   import numpy as np

   final_x    = scope.values[-1, 0]
   final_xdot = scope.values[-1, 1]
