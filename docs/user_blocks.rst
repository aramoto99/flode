.. _user-blocks:

Python blocks in the palette
============================

Audience: people who write their own blocks in Python and want to place them
from the GUI palette like the built-in ones. If you only build models from
Python scripts, ``@block`` (see :doc:`decorator`) works without any of this;
this page is about getting those blocks into the **left pane** and into saved
models.

.. contents::
   :local:
   :depth: 2

Quick start
-----------

1. Create a ``blocks/`` folder in your workspace (the folder passed with
   ``flode --workspace``, or the folder you start ``flode`` in) and put a
   ``.py`` file in it. The examples on this page use ``blocks/filters.py``:

   .. code-block:: python

      from flode import block

      @block(category="Math")
      def gain_offset(t: float, u: float, *, gain: float = 1.0, offset: float = 0.0) -> float:
          """Scale the input and add a constant.

          Args:
              gain: Multiplier applied to the input.
              offset: Constant added after scaling.
          """
          return gain * u + offset

2. Start ``flode`` (or press **Reload** in the left pane if it is already
   running).
3. The block appears in the **Workspace** section at the top of the left pane,
   under the sub-heading *Math*. Drag it onto the canvas, edit ``gain`` and
   ``offset`` in the Inspector, and run the model as usual.

Everything the GUI does with these blocks (placing, saving, running) is the
same as for built-in blocks. A block is drawn as a plain rectangle with its
display name inside and port names beside the ports; its height follows the
port count.

Three ways to write a block
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Form
     - Use it when
     - Notes
   * - ``@block`` on a function
     - Stateless blocks, or small stateful ones, where one function can
       return the output (and the state derivative).
     - Same rules as :doc:`decorator`. Parameters are the keyword-only
       arguments.
   * - ``@block`` on a class
     - You want ``output`` / ``derivative`` / ``update`` as separate methods.
     - Parameters are class fields with defaults.
   * - ``Block`` subclass
     - You need full control: a stateful block with no outputs, custom
       ``__init__``, ``record``, or a shared abstract base class.
     - Call ``super().__init__(n_inputs=..., n_outputs=..., **kwargs)`` and
       store the constructor arguments in ``self._params`` (that dict is what
       gets saved in the model).

A stateful low-pass filter in class form:

.. code-block:: python

   import numpy as np
   from flode import block

   @block(states=1, category="Filters", input_names=("u",), output_names=("y",))
   class LowPass:
       """First-order low-pass filter.

       Args:
           tau: Time constant [s].
       """

       tau: float = 1.0
       x0: float = 0.0

       def output(self, t: float, x: np.ndarray, u: float) -> float:
           return x[0]

       def derivative(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
           return np.array([(u - x[0]) / self.tau])

Source, vector and sink blocks
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**No input (a signal source).** Leave out the ``u`` argument. The number of
input ports becomes 0:

.. code-block:: python

   @block(category="Sources", output_names=("y",))
   def wobble(t: float, *, amplitude: float = 1.0, freq: float = 1.0) -> float:
       return amplitude * float(np.sin(2 * np.pi * freq * t))

**Several ports and vector signals.** Port counts follow the annotations
(``tuple[float, float]``) or ``inputs=`` / ``outputs=``. A port carries a
scalar unless you declare its shape; connecting a vector signal to an
undeclared port is rejected with ``shape.opaque_scalar_island``. Declare the
shapes with ``port_shapes_in`` / ``port_shapes_out`` (details in
:doc:`decorator`):

.. code-block:: python

   @block(port_shapes_in=((3,),), port_shapes_out=((),), category="Vectors")
   def norm3(t: float, u: float) -> float:
       """Euclidean norm of a 3-vector."""
       return float(np.linalg.norm(u))   # u is an ndarray of shape (3,)

**No output (writing to a file, sending over a network).** Declare
``outputs=0`` or annotate the return type ``-> None``:

.. code-block:: python

   @block(outputs=0, sample_time=0.1, category="Sinks")
   def log_value(t: float, u: float, *, path: str = "log.csv") -> None:
       """Append ``t,u`` to a CSV file.

       Args:
           path: File to append to.
       """
       with open(path, "a", encoding="utf-8") as f:
           f.write(f"{t},{u}\n")

Rules for blocks without outputs:

- The function is called **at most once per base time step**, not at every
  intermediate stage of the ODE solver. A discrete block (``sample_time=0.1``
  above) is called only at its own sample times.
- It cannot have states (``states=0`` only) or ``direct_feedthrough=False``;
  ``@block`` raises ``BlockSpecError`` otherwise. Write a stateful no-output
  block as a ``Block`` subclass and implement ``record(self, t, u)``
  (``u[i]`` is the value of input ``i``). A ``Block`` subclass's ``record`` is
  called at every base time step by default; set the class attribute
  ``record_on_sample_hits = True`` to call it only at its own sample times,
  like a no-output ``@block``:

  .. code-block:: python

     class PeakHold(Block):
         """Keeps the largest value seen."""

         block_category = "Sinks"

         def __init__(self, floor: float = 0.0, **kwargs):
             super().__init__(n_inputs=1, n_outputs=0, **kwargs)
             self.floor = floor
             self.peak = floor
             self._params = {"floor": floor}

         def output(self, t, x, u):
             return np.zeros(0)

         def record(self, t, u):
             self.peak = max(self.peak, float(u[0]))

- A return value other than ``None`` is discarded (one warning per block).
- A no-output ``@block`` placed **inside a Subsystem is not called**; the
  simulator logs a warning. Put such blocks at the top level.
- It has no output port, so nothing can be connected after it. To also see a
  signal as a plot, branch the same signal to a ``Scope``.

What shows up in the palette and the Inspector
----------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Item
     - Where it comes from
   * - Sub-heading in the section
     - ``@block(category="Filters")`` (``block_category`` on a ``Block``
       subclass). Blocks without a category sit directly under the section
       heading. Categories are sorted alphabetically and are not translated.
   * - Label
     - ``display_name="Gain with offset"``, or
       ``display_name={"ja": "...", "en": "..."}`` to show a label per UI
       language. Default: the class name.
   * - Tooltip description
     - ``description=...`` (same two shapes as ``display_name``), otherwise
       the first line of the docstring.
   * - Parameter descriptions
     - The ``Args:`` section of the docstring (Google style), or
       ``param_descriptions={"gain": "..."}``. Each description may also be
       ``{"ja": "...", "en": "..."}`` to show it in the UI language (the
       docstring holds one language only). The explicit argument wins
       over the docstring. The docstring is read from the function (function
       form), the class (class form and ``Block`` subclasses), falling back to
       ``__init__`` when the class has no ``Args:``.
   * - Drop-down for a string parameter
     - ``choices={"mode": ("abs", "square")}``. The key must be a parameter,
       the values a non-empty list of distinct strings, and the default must
       be one of them.
   * - Port names
     - ``input_names`` / ``output_names``. **Without them no port name is
       drawn.**
   * - Hidden from the palette
     - ``block_hidden = True`` in the class body (for an abstract base class;
       only that class itself is hidden, subclasses appear).

A block with a choice and a description:

.. code-block:: python

   @block(
       category="Filters",
       choices={"mode": ("abs", "square")},
       param_descriptions={"mode": "How to rectify the signal."},
   )
   def rectify(t: float, u: float, *, mode: str = "abs") -> float:
       return abs(u) if mode == "abs" else u * u

On a ``Block`` subclass, write the same information as class attributes:
``block_category``, ``block_display_name``, ``block_description``,
``block_choices``, ``block_param_descriptions``, ``block_input_names``,
``block_output_names``. ``block_display_name`` and ``block_description`` are
read from the class itself, so a subclass does not inherit its parent's label.
In the class form of ``@block`` these names cannot be used as fields.

Parameter values
^^^^^^^^^^^^^^^^

Numbers (``float`` / ``int`` / ``bool``), arrays (the Inspector accepts an
array literal such as ``[1, 2, 3]``) and strings can be edited in the
Inspector.

Rules to keep
-------------

- **Every parameter needs a default value**, and the default must survive a
  JSON round trip: flode saves it, reads it back, and instantiates the block
  with that value when loading. A required argument, a default that cannot be
  written as JSON, or one whose round-tripped form the constructor rejects
  (for example ``np.array(...)`` coming back as a list and breaking
  ``__init__``) makes that one block a load error.
- **The class name must not equal a built-in block's** (``Scope``, ``Sum``,
  ``Gain`` ...). For a function form the class name is the PascalCase of the
  function name, so ``def scope`` clashes. Pick another name and set the label
  with ``display_name="Scope"``. A subclass such as ``class MyScope(Scope)``
  is fine.
- Files and folders whose name starts with ``_`` are not scanned (they can
  still be imported by other files; ``_helper.py`` below). Names starting with
  ``_`` inside a file, names imported from other modules
  (``from flode.blocks import Gain``) and classes with ``block_hidden = True``
  do not appear either.
- ``blocks/__init__.py`` is **not executed** (the Load errors area shows a
  note). Share code through a module instead:

  .. code-block:: python

     # blocks/uses_helper.py
     from flode import block

     from ._helper import twice     # blocks/_helper.py

     @block
     def doubled(t: float, u: float) -> float:
         return twice(u)

- Sub-folders need an ``__init__.py`` (an empty file is enough). A folder
  without one is not read; if it contains ``.py`` files, the Load errors area
  says so. A block in ``blocks/io/logger.py`` is stored as
  ``flode_ws.io.logger.<class name>``.
- Relative imports work; importing third-party libraries (numpy, scipy ...) is
  unrestricted.
- The ``blocks/`` folder gets no ``__pycache__``: files are always compiled
  from the current source.
- **Type names in saved models.** A block is stored by the name
  ``flode_ws.<file name>.<class name>``, for example
  ``flode_ws.filters.GainOffset``. ``<class name>`` is the name of the
  generated class, so ``def gain_offset`` becomes ``GainOffset``. The
  ``flode_ws`` prefix is virtual: the name does not contain the workspace
  path, so moving the workspace folder does not break saved models. Renaming a
  file, a function or a class does (see below). Blocks from a ``dirs`` entry
  are named ``flode_dirs.<name>.<file>.<class>``; ``modules`` blocks keep their
  real module path.

Editing and reloading
---------------------

After changing a ``.py`` file, press **Reload** (bottom of the left pane, or
*Reload blocks* in the ``...`` menu next to the search box). No server
restart is needed; reloading does not touch the open model or mark it as
changed. A run that is already going keeps the old code; the next run uses
the new one.

- **Load errors.** A file with a syntax error, an exception at import,
  ``sys.exit()``, an invalid block definition, a missing default or a name
  clash is skipped; only that file or block is affected and the rest still
  loads. The collapsible *Load errors* area at the bottom of the left pane
  lists source, path, line and message. The same lines are written to the
  server log.
- **Top-level code runs again on every reload.** Threads or connections that
  your module opened are not closed.
- **A parameter you removed.** The value stays in the model, the Inspector
  warns, and it is **dropped the next time the model is saved or run**. Fix
  the code before saving if you did not mean to remove it. A parameter you
  added is not written into the model; the default is used until you edit it.
- **A port you removed.** Connections to ports that no longer exist are kept
  and drawn as errors. They are not deleted automatically, and running is
  refused until you remove them or restore the port.
- **A block whose .py is gone, unreadable, or broken** (renamed class,
  syntax error ...). The model still opens. The block is drawn as an
  *Unknown block* with its type name; its parameters and connections are kept
  as they are and saving does not change them, but running is refused and
  lists every missing type. Fix the file and reload: the real block comes
  back without reopening the model.
- **Installed packages** (``modules``) are not reloaded; restart the server.
  ``dirs`` folders are reloaded.

Configuration (``~/.flode/config.toml``)
----------------------------------------

Besides ``<workspace>/blocks/``, more sources can be listed in a ``[blocks]``
section (``flode --generate-config`` writes a commented template):

.. code-block:: toml

   [blocks]
   dirs = { lab = "~/lab-blocks" }   # name -> folder
   modules = ["mypkg.blocks"]        # installed packages
   allow_non_loopback = false

- ``dirs``: named folders, read like ``blocks/``. The name must be a Python
  identifier that does not start with ``_``. A relative path is resolved
  against the folder of the config file. They get their own palette sections
  and are reloadable.
- ``modules``: import names of installed packages (``pip install -e`` works).
  Blocks defined in the module itself (and in its sub-modules) are read.
  Not reloadable; restart the server. ``flode`` and ``flode.*`` cannot be
  listed.
- ``allow_non_loopback``: see the next section.

The palette order is: Workspace, then each ``dirs`` entry, then each
``modules`` entry (in the order written), then the built-in categories.
A wrongly typed value (``dirs`` is not a table, a name that is not an
identifier) stops the server at startup; a missing folder or a module that
cannot be imported is shown as a load error and startup continues.

Safety: loading means running the code
--------------------------------------

Loading a block **executes that .py file** with your permissions. The rules:

- With the default, loopback-only start (``127.0.0.1``), the workspace
  ``blocks/`` and the ``[blocks]`` sources are read automatically.
- When you start ``flode`` without ``--workspace``, the folder you started it
  in is the workspace, and its ``blocks/`` is read as well. The only
  exceptions are your home folder and a drive or file-system root. When you
  start ``flode`` in a folder you received from somebody else, **read what is
  in its ``blocks/`` first**. The files that were read are listed in the
  server log and in the tooltip of the section heading.
- When the server listens on a non-loopback address (for example
  ``--host 0.0.0.0``), nothing is read unless you pass
  ``--allow-user-blocks`` or set ``allow_non_loopback = true``. Even then
  reloading from the GUI is refused (blocks are read only at startup), and the
  files API refuses writes, renames, copies and deletes under ``blocks/``.
  ``--allow-python-blocks`` (the Python Function block) does not enable it, and
  the other way round.
- Blocks that are not read show up in the palette as one line with the reason,
  and models using them open with *Unknown block* placeholders.

Using the blocks from Python
----------------------------

``flode.load_blocks`` loads the same blocks, with the same rules, into a
script so that ``Simulator.load`` can resolve the type names. There is no
trust check: whoever runs the script owns the code.

.. code-block:: python

   import flode
   from flode import Simulator

   report = flode.load_blocks("my-workspace")      # reads my-workspace/blocks/
   print(report.errors)                            # () when everything loaded

   sim = Simulator.load("my-workspace/model.flw.json")
   sim.run()

   flode.unload_blocks()                           # forget them again

.. code-block:: python

   flode.load_blocks(
       "my-workspace",
       dirs={"lab": "~/lab-blocks"},     # relative paths: current folder
       modules=["mypkg.blocks"],
       use_config=True,                  # also add [blocks] of ~/.flode/config.toml
       strict=True,                      # default
   )

- ``workspace=None`` reads no workspace (the current folder is not used
  implicitly).
- With ``strict=True`` (the default) a ``BlockLoadError`` is raised after
  everything has been read if any error occurred; ``error.report`` holds the
  details and the blocks that did load stay registered. With ``strict=False``
  inspect the returned report instead.
- Each call replaces everything loaded before, so one process holds one set of
  blocks.
- The blocks can also be used directly: after loading, ``import
  flode_ws.filters`` gives the generated classes, which are instantiated like
  any other block (``flode_ws.filters.GainOffset(gain=2.0, id="g")``).
- ``Simulator.load`` on a model that uses a block that is not loaded raises
  ``UnknownBlockTypeError``; for ``flode_ws.`` / ``flode_dirs.`` names the
  message says to call ``flode.load_blocks(...)``.

.. autofunction:: flode.load_blocks

.. autofunction:: flode.unload_blocks
