# FI-7e redaction and privacy statement

Scope: every checked-in FI-7e text, JSON, script, fixture, and PNG plus the finalized external WebM. The review searches case-insensitively for credential terms (`token`, `key`, `auth`, `cookie`), email syntax, forbidden provider names, absolute Windows/POSIX home paths, non-loopback addresses, and production-host names. Commands are documented in `FI7E_DEMO_RUNBOOK.md`.

Expected contractual words in documentation and source (for example “auth”, “token”, “provider”, and “cookie”) are reviewed false positives. Public football names, the repository URL, loopback addresses, and the explicitly documented Railway caveat are permitted. Generated JSON contains no environment dump. Screenshots and video were visually reviewed for internal identifiers, browser chrome, credentials, personal identity, or developer tools.

Result: zero unresolved secret or privacy findings. The component capture route and dependency shim were disposable and remain outside the PR. The production middleware guard stayed intact. No real account, production session, auth header, cookie, token, API key, email address, personal path, or provider payload is present.
