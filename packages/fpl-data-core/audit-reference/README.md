# audit-reference/

Frozen extraction reference for `fpl-data-core`. **Not importable, not on any
`pythonpath`, not executed by any test or workflow.**

The canonical, actively-developed package is `fpl_data_core/`.

`schemas.py` and `season_registry.py` are preserved here because
`fpl_data_core/schemas.py` and `fpl_data_core/season_registry.py` each label them
*"audit copy — do not modify"*. They are kept byte-for-byte, including internal
path headers that still read `fpl-data-core/python/...` — the pre-rename path,
left deliberately so the audit record stays faithful to what was extracted.

`stat_calculator.py` was **deleted** rather than preserved: it carried no
audit-copy designation from any canonical module and no live consumer, and
`PACKAGE_AUDIT.md` flags its `make_discrete()` / `calculate_discrete_gameweek_stats()`
as **RETIRE — duplicates upstream `fpl-elo-insights` logic**. Its one non-retired
function, `compute_rolling_xgi_per_90()`, had already been promoted to
`fpl_data_core/analytics.py`.

## Why the directory was renamed

This was `packages/fpl-data-core/python/` until 2026-08-07. Three packages each
shipped a directory literally named `python/`, and several `pytest.ini` files put
those package roots on `sys.path` — so the bare top-level name `python` resolved
to whichever one was imported first, by import-order luck.

## Why the hyphen — do not "fix" it to `audit_reference`

`audit-reference` is deliberately **not a valid Python identifier**, which is the
only reliable way to keep a directory sitting directly inside a `sys.path` entry
from being importable. `../fpl-data-core` is on several `pytest.ini` `pythonpath`
lists, so an importable name here would be reachable from other packages.

Deleting `__init__.py` is *not* sufficient: under PEP 420 the directory would
become an implicit **namespace package**, leaving `audit_reference` importable and
merged with `fpl-api-client/audit_reference/` — recreating a smaller version of
the very collision this cleanup removed. See that package's
`audit-reference/README.md` for the demonstration.
