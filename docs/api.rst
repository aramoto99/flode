API Reference
=============

This page documents the public API. Internal helpers (prefixed ``_``) are
omitted.

Block base class
----------------

.. autoclass:: pyflw.Block
   :members: output, derivative, update
   :undoc-members:
   :show-inheritance:

Simulator
---------

.. autoclass:: pyflw.Simulator
   :members: add, connect, run, get_block, rename
   :undoc-members:
   :show-inheritance:

``@block`` decorator
--------------------

.. autofunction:: pyflw.block

Exceptions
----------

.. automodule:: pyflw.exceptions
   :members:
   :undoc-members:
   :show-inheritance:
