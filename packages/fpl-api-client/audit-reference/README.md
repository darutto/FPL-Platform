# audit-reference/

Frozen extraction reference for `fpl-api-client`. **Not importable, not on any
`pythonpath`, not executed by any test or workflow.**

The canonical, actively-developed client is `fpl_api_client/` — see
`packages/fpl-historical/CONTRACT.md`: *"all edits go to
`fpl_api_client/fpl_client.py`"*.

## Why the directory was renamed

This was `packages/fpl-api-client/python/` until 2026-08-07. Three packages each
shipped a directory literally named `python/`, and several `pytest.ini` files put
those package roots on `sys.path` — so the bare top-level name `python` resolved
to whichever one was imported first. Nothing imported *this* copy by that name,
but its presence kept the collision surface alive.

## Why the hyphen — do not "fix" it to `audit_reference`

`audit-reference` is deliberately **not a valid Python identifier**, which is the
only reliable way to keep a directory that sits directly inside a `sys.path`
entry from being importable.

Deleting `__init__.py` is *not* sufficient. Under PEP 420, a directory without
`__init__.py` becomes an implicit **namespace package** — so `audit_reference`
stayed importable and, worse, merged across this directory and
`fpl-data-core/audit_reference/` simultaneously:

```
>>> import audit_reference
>>> audit_reference.__path__
_NamespacePath(['.../fpl-data-core/audit_reference', '.../fpl-api-client/audit_reference'])
```

That is the same mechanism that made the old bare `python/` directories collide.
Renaming to a hyphenated form makes `import audit_reference` fail with
`ModuleNotFoundError` and `import audit-reference` a `SyntaxError` — unreachable
by any import statement.

## Why the file headers still say `python/`

`fpl_client.py` and `football_data_client.py` are labelled *"audit copy — do not
modify"* by the canonical package's docstrings. They are preserved byte-for-byte,
including their internal path headers, which therefore still read
`packages/fpl-api-client/python/...`. That is the pre-rename path — kept
deliberately rather than corrected, so the audit record stays faithful to what
was extracted.
