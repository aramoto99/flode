flode documentation
===================

**flode** is a block-diagram dynamic system simulator for Python.
Build continuous, discrete, and hybrid models by connecting pre-built blocks,
then integrate with ``scipy.solve_ivp``.

**Stable as of v0.14.0** (2026-05-09, ADR-0039): the public API
(``Block`` / ``Simulator`` / 38 built-in blocks / linearize / Bode /
``Simulator.compile()``), the JSON model schema 0.8, the REST endpoint
family ``/api/v1/*``, and the extras names
(``flode[control/codegen/gpu]``) are frozen under SemVer; subsequent
breaking changes require v3.0. v1.0 was released the same day but
ADR-0039 immediately corrected ``Subsystem`` port semantics (= internal
``Inport`` / ``Outport`` are SSOT, outer ``n_inputs`` / ``n_outputs``
derived) before PyPI publish.

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
