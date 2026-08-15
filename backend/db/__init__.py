"""AlphaDesk persistence layer.

Scaffolding only as of card F1: nothing in `api.main` or the agents imports
this package yet. It holds the identity/link tables (`db.models`), the async
engine + FastAPI session dependency (`db.session`) and the token-at-rest
encryption helpers (`db.crypto`).

Import as `db.*` — the backend has no `backend.` package prefix.
"""
