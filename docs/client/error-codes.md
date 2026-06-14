# Client error codes

User-facing errors carry a stable numeric code in parentheses — e.g. `(Error 47)` — so
players can report a problem without us having to expose internals (URLs, hosts, stack
traces) in the message itself. The code is the lookup key into this table.

Codes are arbitrary, stable identifiers (not Godot/HTTP status values). Once assigned, a
code never changes meaning. Pick the next free number when adding one.

| Code | Where | Meaning | Likely cause / fix |
|------|-------|---------|--------------------|
| 47 | Login / API request ([`auth_manager.gd`](../../client/autoload/auth_manager.gd) `_format_request_result_error`) | TLS handshake with the API server failed — the request never reached the application layer. | The client is pointed at an HTTPS endpoint whose certificate could not be negotiated. Check `api_base_url` in `client_config.json` (override via `user://client_config.json`). For local dev this should be `http://localhost:8080`, not the production HTTPS host. |

## Adding a code

1. Append `(Error NN)` to the user-facing message in the client, with the next free `NN`.
2. Add a row here describing where it fires, what it means, and how to resolve it.
3. Leave a `# See docs/client/error-codes.md` comment at the call site.
