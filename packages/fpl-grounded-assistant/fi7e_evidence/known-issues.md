# Known issues

- Railway `fpl-backend` has a pre-existing, service-specific deployment issue. FI-7e does not use that service, retry it, fix it, or reconfigure it. Local deterministic validation is the completion gate; this artifact package does not claim Railway is healthy.
- ESLint has no repository configuration and is therefore not introduced or claimed as a gate. Jest, TypeScript, the production build, and the repository contract gate are recorded instead.
- The silent WebM is a new immutable release asset outside Git. The blocked `ca2b82db...` recording is superseded and is not referenced by this package. Screenshots, transcript, response hashes, and trace remain the fallback if external availability later changes.
- F2 visual evidence shows the preserved primary response. The throwing evidence-subtree behavior is causally established by the focused `EvidenceBoundary` test and its trace assertion; no production failure hook was added.
- The seven screenshots use the sanctioned component-level capture alternative: a disposable, uncommitted render route mounted the unchanged `MessageList`, `EvidenceBoundary`, and evidence components against the loopback fixture payloads. No middleware guard, authentication control, credential, token, `.env`, or auth fixture was changed or committed.
- The checked-in package contains 23 artifact-only paths. Runtime-path observations and the static/offered-tool, FI invocation, M1-M5, replay, enrichment, and UI-request counters are recorded per scenario in `backend-trace.json`.
