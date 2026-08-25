flode documentation
===================

**flode** is a block-diagram dynamic system simulator for Python.
Build continuous, discrete, and hybrid models by connecting pre-built blocks,
then integrate with ``scipy.solve_ivp``.

**Stable as of v0.14.0** (2026-05-09, ADR-0039): the public API
(``Block`` / ``Simulator`` / built-in blocks / linearize / Bode), the
JSON model schema, the REST endpoint family ``/api/v1/*``, and the
extras names (``flode[control]``) follow ZeroVer: a **minor** bump may
carry breaking changes (noted in the changelog), a **patch** bump never
does. ADR-0039 corrected ``Subsystem`` port semantics (= internal
``Inport`` / ``Outport`` are SSOT, outer ``n_inputs`` / ``n_outputs``
derived) on the same day. The experimental JAX / GPU path
(``Simulator.compile()``, ``linearize(method="jax")``,
``flode[codegen/gpu]``) was removed in v0.48.0.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   quickstart
   blocks
   decorator
   analysis
   api

For internal design documents (ADRs, SPEC-0001), see ``.claude/docs/``.

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
