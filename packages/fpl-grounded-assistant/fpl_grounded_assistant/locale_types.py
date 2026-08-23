"""fpl_grounded_assistant.locale_types
======================================
Phase F0 of the language track: the locale carrier.

Defines the ``Locale`` type and the process-wide default. Resolution happens
once at the HTTP request boundary (``fpl_server.py``) and the resolved value
is threaded down to the text producers (renderer, final_response builders,
squad_solver, deterministic fallback messages).

Named ``locale_types`` rather than ``locale`` to avoid shadowing the stdlib
``locale`` module — several test files in this package load modules
standalone via ``importlib.util`` with the package directory on ``sys.path``
(bypassing ``fpl_grounded_assistant/__init__.py``), and a same-named module
there would win over the stdlib one process-wide.

This module intentionally contains no translation, no ``gettext``/``babel``
dependency, and no per-string logic. It is the empty carrier that F1 (the
string catalogue) and F2/F3 (real resolution + system-prompt wiring) build on
top of. See the language-track F0 plan for the phase boundaries.
"""
from __future__ import annotations

from typing import Literal

#: The two supported locales for this phase.
Locale = Literal["es", "en"]

#: Spanish-first product default (matches the existing orchestrator system
#: prompt policy: "OUTPUT: terse, structured, action-oriented. Spanish-first.").
DEFAULT_LOCALE: Locale = "es"
