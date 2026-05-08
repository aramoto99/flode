pyflw documentation
===================

**pyflw** is a block-diagram dynamic system simulator for Python.
Build continuous, discrete, and hybrid models by connecting pre-built blocks,
then integrate with ``scipy.solve_ivp``.

**Stable as of v0.13.0** (2026-05-09, ADR-0038): the public API
(``Block`` / ``Simulator`` / 38 built-in blocks / linearize / Bode /
``Simulator.compile()``), the JSON model schema 0.7, the REST endpoint
family ``/api/v1/*``, and the extras names
(``pyflw[gui/control/codegen/gpu]``) are frozen under SemVer; subsequent
breaking changes require v2.0.

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
