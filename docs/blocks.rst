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
   flode.blocks.Add
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

.. _user-function:

User Function
-------------

Blocks whose behaviour is written by the user.

- ``Fcn`` evaluates a single expression ``y = f(t, u)`` in an AST-whitelisted
  sandbox (no imports, no statements). **Prefer it whenever the logic fits in
  one expression** — a model that only uses ``Fcn`` never executes arbitrary
  code when it is run.
- ``PythonFunction`` embeds a complete ``@block``-style Python source in the
  model (``params.code``) and is **not sandboxed**: running a model that
  contains one executes that code with your privileges. Port counts, state
  size, ``sample_time`` and the parameter list are derived from the source by
  static analysis (no ``exec``) so the diagram stays consistent while you
  edit; the code itself runs exactly once, right before ``Simulator.run()``
  resolves the execution order. Opening or editing a model never runs it.

  On the server, Python Function blocks are always allowed on a loopback bind
  (``127.0.0.1`` / ``localhost`` / ``::1``). On any other address they are
  refused unless ``flode --allow-python-blocks`` (or
  ``[server] allow_python_blocks = true``) is given. The GUI additionally asks
  for confirmation the first time a model with Python code is run and remembers
  the answer per model until the code changes — this is a convenience, not a
  security boundary.

.. autosummary::
   :toctree: _autosummary
   :nosignatures:

   flode.blocks.PythonFunction

Since v0.50.0 the Inspector can edit the port structure of a
``PythonFunction`` block (input/output counts and per-port names declared with
``@block(input_names=..., output_names=...)``). These edits are performed by
**rewriting the source** through a static AST-based endpoint — the code remains
the single source of truth, nothing is executed, and the rewritten source is
re-analysed and verified before it is saved.

Since v0.51.0 the parameter list (the keyword-only arguments after ``*``) can
also be edited from the Inspector: parameters can be **added** (``float`` /
``int`` / ``bool`` / ``str`` with a default), **removed**, and **renamed**.
Two rules are worth knowing:

- **Parameter names are Python identifiers** (ASCII, non-keyword, at most 64
  characters) — unlike port names, which are display captions and may contain
  spaces or emoji. Renaming rewrites the identifier everywhere it refers to the
  parameter (including closures) and refuses constructs it cannot rewrite
  safely (f-strings referencing the name, ``match`` captures, ``global`` /
  ``nonlocal``, nested ``class`` definitions, dynamic access via ``locals()`` /
  ``eval``); in those cases edit the code directly.
- **Removing a parameter does not touch the function body.** If the body still
  references the removed name, the model fails at run time with a
  ``NameError`` reported with the block id and line number — fix the body
  yourself after removing a parameter, exactly like a port-count reduction
  leaving a stale ``u[2]`` behind.

Since v0.52.0 each parameter row also shows the declared *type* and lets you
change it (``float`` / ``int`` / ``bool`` / ``str``). Retyping rewrites the
annotation and the default literal together; the default and any configured
value are carried over when they convert cleanly (float⇄int truncates,
numbers stringify, strings parse back into numbers when possible — ``bool``
never converts implicitly), otherwise they reset to the new type's neutral
default (``0.0`` / ``0`` / ``False`` / ``""``).
