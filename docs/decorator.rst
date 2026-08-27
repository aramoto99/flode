``@block`` Decorator
====================

The ``@block`` decorator converts a plain Python function into a ``Block``
subclass without writing a class by hand. It infers port counts and
``direct_feedthrough`` from the function signature and type annotations.

.. note::

   **Phase 1 supports the function form only.** Applying ``@block`` to a
   class raises ``NotImplementedError``. Direct ``Block`` subclassing
   remains the recommended approach for class-based blocks in Phase 1.
   Class-form support is planned for Phase 2.

Function signature convention
------------------------------

The positional arguments must follow this order:

- Combinational (no state): ``(t, u)`` or ``(t,)``
- Stateful: ``(t, x, u)`` or ``(t, x)``

Keyword-only arguments become block *parameters* (set at construction time,
not updated during simulation).

Return type annotation
^^^^^^^^^^^^^^^^^^^^^^

- Combinational: return the output directly (``float``, ``tuple[float, ...]``)
- Stateful: return ``tuple[<output>, np.ndarray]`` where the second element is
  ``x_dot`` (continuous) or ``x_next`` (discrete)

Port count inference
--------------------

``n_inputs`` and ``n_outputs`` are inferred from type annotations:

- ``float`` / ``int`` / ``np.float64`` annotation → 1 port
- ``tuple[float, float]`` (fixed-length) → 2 ports
- Explicit ``@block(inputs=N)`` or ``@block(outputs=N)`` override inference

Example 1: Minimal (combinational, no state)
--------------------------------------------

.. code-block:: python

   from flode import block

   @block
   def double(t: float, u: float) -> float:
       return 2.0 * u

   blk = double(id="dbl")   # Block subclass; instantiate with keyword args

``n_inputs=1``, ``n_outputs=1``, ``direct_feedthrough=True`` are all inferred
automatically.

Example 2: Stateful block (continuous integrator)
--------------------------------------------------

.. code-block:: python

   import numpy as np
   from flode import block

   @block(states=1)
   def my_integrator(
       t: float,
       x: np.ndarray,
       u: float,
       *,
       x0: float = 0.0,
   ) -> tuple[float, np.ndarray]:
       y = x[0]
       x_dot = np.array([u])
       return y, x_dot

   blk = my_integrator(x0=1.0, id="integ")

- ``states=1`` declares one continuous state variable.
- The ``x0`` keyword-only argument is treated as the initial condition and is
  stored in ``block.x0`` automatically.
- ``direct_feedthrough`` defaults to ``False`` when ``states > 0``.

Example 3: MIMO block
---------------------

When port counts cannot be inferred from type annotations, use explicit
``inputs=`` / ``outputs=``:

.. code-block:: python

   import numpy as np
   from flode import block

   @block(inputs=2, outputs=2)
   def swap(t: float, u: np.ndarray) -> np.ndarray:
       return np.array([u[1], u[0]])

   blk = swap(id="swap")

API reference
-------------

.. automodule:: flode.core.decorator
   :members: block
   :undoc-members:
   :show-inheritance:

Design notes
------------

- If ``u`` has a ``float``/``int``/``np.float64`` annotation, it is passed to
  the function as a Python ``float`` (not an array). If it is annotated as a
  fixed-length ``tuple``, each element is unpacked as ``float``. With
  ``inputs=N``, the raw ``np.ndarray`` is passed.
- When ``states > 0`` and ``sample_time`` is ``None`` or ``0.0``, the second
  return value is treated as ``x_dot``. When ``sample_time > 0``, it is
  ``x_next``.
- The ``u`` argument is evaluated twice per time step in Phase 1 (once in
  ``output()``, once in ``derivative()``). For expensive functions, consider
  direct ``Block`` subclassing with manual caching.

Writing the same source in the GUI (Python Function block)
----------------------------------------------------------

The ``PythonFunction`` block (palette category *User Function*) accepts a
``@block``-style source string and applies **the same inference engine** as
the decorator, so a function that works with ``@block`` in Python works
unchanged when pasted into the block. Two restrictions apply because the
structure is derived without executing the code:

- ``@block(...)`` arguments and parameter defaults must be literals
  (``@block(states=N)`` with ``N`` defined elsewhere is rejected), and
- type annotations must use the built-in vocabulary (``float``, ``int``,
  ``bool``, ``str``, ``tuple[...]``, ``np.float64``, ``np.ndarray``,
  ``npt.NDArray[...]``, ``Any``). Module-level aliases are not resolved;
  declare the structure explicitly with ``@block(inputs=N, outputs=M)``
  instead.

Only the function form is accepted in the block; class-form ``@block`` is
rejected with a message. See :ref:`the block library <user-function>` for the
security model of ``PythonFunction``.
