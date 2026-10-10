---
title: Testing
description: Running the Price Manager test suite.
---

Postgres required. Tests read `DATABASE_URL` (default
`postgresql://postgres:postgres@localhost:5432/test` — matches the CI service). Run via `make test`.
