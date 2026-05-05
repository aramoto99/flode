"""Sphinx configuration for pyflw."""

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# -- Project information -------------------------------------------------------

project = "pyflw"
author = "aramoto99"

try:
    from pyflw import __version__  # type: ignore[attr-defined]

    release = __version__
except (ImportError, AttributeError):
    release = "0.0.1"

version = release

# -- General configuration -----------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
]

master_doc = "index"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Napoleon (Google docstring) -----------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = False

# -- Autodoc -------------------------------------------------------------------

autodoc_typehints = "description"
autodoc_member_order = "bysource"
autosummary_generate = True

# -- HTML output ---------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path: list[str] = []
