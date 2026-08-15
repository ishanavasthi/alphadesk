"""Application services — logic that is neither a route nor a connector.

A service owns a *job*: something with a beginning, an end and a report, which
several callers (an HTTP route, a cron trigger, a background task) all want to
run the same way. `services.snapshots` is the first one.

Import as `services.*` — the backend has no `backend.` package prefix.
"""
