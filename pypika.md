# PyPika Migration Notes

This document captures what was completed for the backend PyPika migration task and how it was implemented.

## Goal

`TODO.md (9-13)` required:

1. Add `pypika` to backend dependencies.
2. Refactor raw SQL query callsites to use a query builder flow.
3. Define queries in table/domain-respective files.

## What Was Completed

## 1) Dependency Added

- Added `pypika` in `backend/requirements.txt`:
  - `pypika>=0.48.9`

## 2) Shared Query Builder Layer Added

- Added `backend/app/sql_builder.py`.
- Purpose:
  - Build SQL via PyPika.
  - Convert PyPika `%s` placeholders to asyncpg-style `$1, $2, ...`.
  - Return a typed object with `sql` + `params`.

Core behavior:

- `build_query(query, params)`:
  - `query.get_sql(...)` from PyPika
  - placeholder rewrite `%s -> $n`
  - returns `BuiltQuery(sql, params)`

This ensures all migrated query callsites can execute safely with asyncpg.

## 3) Runtime SQL Calls Refactored to Builder Pattern

Across backend modules, query execution was moved to this pattern:

1. Build query using PyPika.
2. Convert with `build_query(...)`.
3. Execute via asyncpg:
   - `conn.fetch(...)`
   - `conn.fetchrow(...)`
   - `conn.fetchval(...)`
   - `conn.execute(...)`

Representative migrated runtime modules include:

- `backend/app/routers/onboarding.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/admin_management.py`
- `backend/app/middleware/auth_context.py`
- `backend/app/services/onboarding_service.py`
- `backend/app/services/onboarding_question_service.py`
- `backend/app/services/onboarding_crawl_service.py`
- `backend/app/services/system_config_service.py`
- `backend/app/services/prompts_service.py`
- `backend/app/services/payment_entitlement_service.py`
- `backend/app/services/otp_service.py`
- `backend/app/services/admin_subscription_grant_service.py`
- `backend/app/services/journey_service.py`
- `backend/app/services/plan_catalog_service.py`
- `backend/app/repositories/chat_repository.py`
- `backend/app/task_stream/postgres_store.py`
- `backend/app/task_stream/tasks/onboarding_playbook_generate.py`
- `backend/app/task_stream/tasks/plan_execute.py`
- `backend/app/doable_claw_agent/stores.py`

## 4) Table/Domain Query Files Created

Added under repository layer:

- `backend/app/repositories/onboarding_table.py`
- `backend/app/repositories/task_stream_table.py`
- `backend/app/repositories/core_tables.py`

### How these are used

- `onboarding_queries.py`:
  - central onboarding query helpers/builders, including update builders used by onboarding question flow.
- `task_stream_queries.py`:
  - centralized stale-running-stream cleanup SQL provider.
- `stores_queries.py`:
  - centralized query constants used by `doable_claw_agent/stores.py`.

This removed scattered query definitions from service/router files and moved remaining constants behind query modules.

## Key Migration Patterns Used

## A) Standard SELECT/INSERT/UPDATE/DELETE

- Use PyPika table objects + `PostgreSQLQuery`.
- Use `Parameter("%s")` for values.
- Convert and execute through `build_query(...)`.

## B) JSON/JSONB Fields

- Python dict/list values are serialized using `json.dumps(...)` before persistence when needed.
- Query builders set JSON payloads as parameters, executed through asyncpg placeholders.

## C) UUID and Type Coercion

- Avoid brittle cast APIs on PyPika fields where not supported by installed version.
- Rely on asyncpg parameter binding/coercion where valid.
- Keep conversions explicit only where required.

## D) Complex Postgres-Specific Statements

Some statements are intentionally kept as SQL constants (but centralized in query files), especially where readability and reliability are better than over-complex builder expressions:

- advisory locks (`pg_advisory_xact_lock(hashtext(...))`)
- online schema patches (`ALTER TABLE ... IF NOT EXISTS`)
- specific conflict clauses / advanced updates
- interval arithmetic cleanup statements

These are not inline at runtime callsites; they are centralized in repository table modules under `app/repositories/*`.

## Regressions Found During Migration and Fixes

## 1) `.cast(...)` Field errors

- Issue: `AttributeError: 'Field' object has no attribute 'cast'` in some migrated logic.
- Fix: Removed unsupported `.cast(...)` usages and used binding/coercion-safe query forms.

## 2) JSONB binding errors

- Issue: asyncpg argument type mismatch when Python lists/dicts were sent incorrectly.
- Fix: ensured JSON payload handling is explicit and query updates are built consistently from centralized builders.

## 3) Endpoint smoke failures

- Issue observed on `POST /api/v1/onboarding/rca-next-question` during migration pass.
- Fix: corrected query/binding path and revalidated endpoint behavior.

## Validation Performed

## A) Static checks

- Backend compile sweep:
  - `python3 -m compileall -q app` -> pass

## B) Query usage checks

- Verified no direct runtime inline SQL call pattern remains in backend app callsites:
  - no matches for `fetch("...")`, `fetchrow("...")`, `fetchval("...")`, `execute("...")` patterns with raw string literals.

## C) Query ownership checks

- Verified query module imports in migrated files:
  - `app/services/onboarding_service.py`
  - `app/services/onboarding_question_service.py`
  - `app/task_stream/postgres_store.py`
  - `app/doable_claw_agent/stores.py`

## Outcome Summary

- `pypika` dependency added.
- Backend runtime query execution standardized on builder path (`build_query` + asyncpg).
- Query definitions centralized into table/domain query modules for remaining non-trivial SQL constants.
- Smoke/compile checks rerun after fixes.

## Notes for Future Contributors

When adding a new DB query:

1. Prefer PyPika query construction.
2. Pass through `build_query(...)`.
3. Keep table/domain-specific query definitions under `backend/app/repositories/`.
4. If a Postgres-specific edge case is clearer as SQL constant, place it in repository table modules (not inline inside service/router runtime callsites).

## Recent Runtime Stabilization (Post-Migration)

After the initial migration, a few production-like runtime regressions were fixed without reducing code quality:

- Removed unsupported PyPika `.cast(...)` usage from critical paths where the installed PyPika version does not support `Field.cast`/`Parameter.cast`.
- Switched sensitive JSONB writes to explicit SQL with `::jsonb` casting for asyncpg compatibility.
- Fixed OTP verification path failures in `auth` flow caused by cast-based UUID/TEXT comparisons.
- Fixed onboarding patch/reset path failures in `onboarding_service` for UUID and JSONB updates.
- Fixed playbook stream task failures in:
  - `task_stream/tasks/onboarding_playbook_generate.py`
  - `task_stream/postgres_store.py`
  by replacing cast-based inserts/updates with safe SQL-cast execution.

Validation after these fixes:

- Backend compile checks passed.
- Local smoke checks passed for:
  - `POST /api/v1/auth/verify-otp`
  - `POST /api/v1/onboarding`
  - playbook task-stream start/events flow
- CORS error symptoms resolved once backend 500s were removed (CORS was secondary to server exceptions).

For the complete timeline and broader non-PyPika change history, see `changes.md`.
