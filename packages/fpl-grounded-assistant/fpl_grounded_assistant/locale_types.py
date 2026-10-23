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

#: i18n S3: the key a request's locale travels under to the TOOL handlers, on the
#: per-request shallow copy of the bootstrap -- the same mechanism as
#: ``_my_team_id`` (i39), for the same reason: tool handlers are called as
#: ``handler(args, bootstrap)`` and build user-visible text (comparison reasons,
#: verdicts, card labels) inside the tool, where no locale parameter exists. The
#: harness sets it ONLY for a non-default locale, on a copy -- never on the
#: shared server-level bootstrap, and never for ``es`` (an es turn sees exactly
#: the bootstrap it always did).
BOOTSTRAP_LOCALE_KEY: str = "_locale"


def bootstrap_locale(bootstrap: object) -> Locale:
    """The locale a tool handler should write in: the request's, else the default."""
    if isinstance(bootstrap, dict):
        value = bootstrap.get(BOOTSTRAP_LOCALE_KEY)
        if value == "en":
            return "en"
    return DEFAULT_LOCALE
