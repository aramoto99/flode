API Reference
=============

This page documents the public API. Internal helpers (prefixed ``_``) are
omitted.

Block base class
----------------

.. autoclass:: flode.Block
   :members: output, derivative, update
   :undoc-members:
   :show-inheritance:

Simulator
---------

.. autoclass:: flode.Simulator
   :members: add, connect, run, get_block, rename
   :undoc-members:
   :show-inheritance:

``@block`` decorator
--------------------

.. autofunction:: flode.block

Exceptions
----------

.. automodule:: flode.exceptions
   :members:
   :undoc-members:
   :show-inheritance:
