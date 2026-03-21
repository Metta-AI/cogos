# CogOS — High-Value Improvement Suggestions

## Overview

CogOS is an autonomous software engineering agent built on the Viable System Model, with ~300 source files across 6 packages (`cogos`, `cogtainer`, `dashboard`, `memory`, `cli`, `cogents`). The codebase has solid test coverage (179 test files) and good use of Pydantic models. Below are the highest-impact improvements ordered by value.

---

## 1. CRITICAL: Unify the Two Repository Classes

**Problem:** There are two completely separate `Repository` classes:
- `src/cogos/db/repository.py` (2,322 lines) — CRUD for CogOS tables
- `src/cogtainer/db/repository.py` (1,854 lines) — CRUD for cogtainer tables

Both use the RDS Data API with nearly identical patterns: same `_exec` helpers, same row-mapping logic, same error handling. This is ~4,200 lines of duplicated patterns.

**Impact:** Bug fixes and improvements must be applied in two places. Inconsistencies creep in (e.g., one has better error handling than the other).

**Suggestion:** Extract a shared `BaseRepository` with the common RDS Data API plumbing (execute, row mapping, transaction helpers). Each domain repository inherits and adds only its domain-specific methods.

---

## 2. HIGH: Replace Silent Exception Swallowing

**Problem:** Many critical code paths catch `Exception` and either `pass` or log at `debug` level, masking real failures:

- `src/cogtainer/local_dispatcher.py:46-86` — Every step of the dispatcher tick is wrapped in bare `except Exception: logger.debug(...)`. If the heartbeat, reaper, throttle check, or scheduler fails, the error is essentially invisible.
- `images/cogos/cogos/init.py:16-52` — 9 functions with bare `except: pass` (completely silent failures)
- `src/dashboard/app.py` — Multiple generic exception handlers

**Impact:** Production issues go undetected. When debugging, there's no trace of what actually failed.

**Suggestion:**
1. Catch specific exception types, not bare `Exception`
2. Log at `warning` or `error` level for unexpected failures, not `debug`
3. Remove all `except: pass` blocks — at minimum log the exception
4. Add structured context (run_id, process_id, cogent_name) to log messages

---

## 3. HIGH: Add Timeouts to All External HTTP Calls

**Problem:** External API calls lack explicit timeouts:

- `src/cogtainer/cloudflare.py` — All Cloudflare DNS API calls via `requests` have no timeout
- `src/cogos/io/github/sender.py` — GitHub API calls without timeout
- `src/cogtainer/update_cli.py` — AWS API calls in deployment scripts

**Impact:** A single hung external call can block the entire dispatcher tick, executor, or deployment for minutes/hours with no visibility.

**Suggestion:** Add explicit `timeout=30` (or appropriate value) to every `requests.get/post/put/delete` call. Consider a shared HTTP session with default timeout configured once.

---

## 4. HIGH: Defensive Array/Dict Access

**Problem:** Multiple locations access `[0]` on lists without checking emptiness:

- `src/cogtainer/cloudflare.py:188` — `existing[0]["id"]` (DNS record lookup)
- `src/cogtainer/update_cli.py:365` — `describe_services(...)["services"][0]`
- `src/cogtainer/update_cli.py:870` — `token_resp["authorizationData"][0]`
- `src/dashboard/routers/cron.py:63` — `existing[0]`
- `src/cogos/executor/handler.py:530` — `refs[0]` without bounds check

**Impact:** Any of these will raise `IndexError` in edge cases, crashing the process.

**Suggestion:** Add a simple guard before each indexed access:
```python
if not existing:
    raise ValueError("Expected DNS record not found")
record_id = existing[0]["id"]
```

---

## 5. HIGH: Eliminate Global Mutable State

**Problem:** Several modules use mutable globals with lazy initialization:

- `src/cogos/executor/handler.py:85` — `_RUNTIME = None` with `global _RUNTIME`
- `src/dashboard/app.py:19,24` — `_cached_admin_key` global
- `src/cogtainer/io/email/handler.py:36,43` — `_rds` and `_dynamo_table` globals
- `src/cogtainer/aws.py:27` — `_profile` global
- `src/cogtainer/deploy_config.py:16` — `_config_cache` global

**Impact:** Makes code harder to test (must patch globals), creates hidden coupling, and risks race conditions in concurrent contexts.

**Suggestion:** Use dependency injection via function parameters or a lightweight DI container. For Lambda handlers where DI is impractical, use `functools.lru_cache` on a factory function instead of bare globals.

---

## 6. MEDIUM: Extract Hardcoded Constants

**Problem:** Magic numbers scattered throughout:

- `src/cogtainer/local_dispatcher.py:18-20` — `_THROTTLE_COOLDOWN_MS = 300_000`, `_TICK_INTERVAL = 60`
- `src/cogtainer/local_dispatcher.py:60` — `900_000` (15-min stale run timeout)
- `src/cogos/executor/handler.py:50,56` — Spill thresholds (4000, 1000)
- `src/cogos/io/discord/bridge.py:286,670,722,852` — Sleep durations (60s, 300s, 5s)
- `src/cogtainer/cdk/stacks/account_stack.py:45` — `k=6` for random token length

**Impact:** Hard to tune behavior without reading implementation details. Risk of inconsistent values when the same concept is expressed in multiple places.

**Suggestion:** Create a `constants.py` or use the existing config/settings patterns to centralize these values. At minimum, ensure every magic number has a named constant with a docstring.

---

## 7. MEDIUM: Improve Retry/Backoff Patterns

**Problem:** Retry logic uses fixed sleep intervals instead of exponential backoff:

- `src/cogos/executor/handler.py:242-247` — Polls for a dispatch run with `time.sleep(0.2)` × 5 attempts
- `src/cogtainer/local_dispatcher.py:135-139` — Sleeps 1 second × 60 between ticks
- `src/cogos/io/discord/bridge.py` — Fixed 60s/300s reconnect sleeps

**Impact:** Fixed delays are either too slow (wasting time) or too aggressive (hammering services). No jitter means thundering herd issues.

**Suggestion:** Use `tenacity` or a simple exponential backoff helper:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=0.2))
def wait_for_run(repo, run_id):
    run = repo.get_run(run_id)
    if not run:
        raise RetryError("Run not ready")
    return run
```

---

## 8. MEDIUM: Address `exec()` Security Surface

**Problem:** Multiple locations use `exec()` to load Python code:

- `src/cogos/cog/cog.py:69` — `exec(compile(cog_py.read_text(), ...))` for cog definitions
- `src/cogos/image/spec.py:150,181` — `exec()` in image spec parsing
- `src/cogos/sandbox/executor.py:235` — `exec()` in sandbox
- `src/cogos/capabilities/cog_registry.py:67` — `exec()` for make_coglet

**Impact:** While these operate on trusted cog definition files (not user input), the `exec()` surface is broad and any path traversal or file injection vulnerability would escalate to RCE.

**Suggestion:**
1. Document the security assumptions clearly (which files are trusted, why)
2. Validate file paths are within expected directories before `exec()`
3. Consider replacing `exec()` with `importlib.import_module()` for cog loading where possible
4. Use `RestrictedPython` for the sandbox executor

---

## 9. MEDIUM: Improve Test Coverage for Critical Paths

**Problem:** While test coverage is generally good (179 test files for 301 source files), some critical modules are under-tested:

- `src/cogtainer/cloudflare.py` — No dedicated test file (DNS management)
- `src/cogtainer/io/email/handler.py` — No tests for email IO handler
- `src/cogos/io/discord/bridge.py` — Complex 900+ line file with only basic tests
- `src/cogtainer/tools/` — Limited testing for sandbox tools
- `src/cogos/runtime/` — Runtime factory and local runtime have minimal tests

**Impact:** Changes to these modules have high regression risk.

**Suggestion:** Prioritize tests for `cloudflare.py` (infrastructure), `email/handler.py` (IO path), and `runtime/` (core orchestration). Use mocking for external APIs.

---

## 10. MEDIUM: Standardize Configuration Loading

**Problem:** Configuration is loaded through multiple patterns:
- `ExecutorConfig` dataclass from env vars (`handler.py:73-82`)
- `_config_cache` global dict (`deploy_config.py`)
- `_config` global from SSM (`lambdas/shared/config.py`)
- Direct `os.environ` access scattered throughout
- Pydantic `Settings` in some places

**Impact:** No single source of truth for configuration. Hard to know what env vars are required. Different validation behavior across modules.

**Suggestion:** Standardize on Pydantic `Settings` (already a dependency) for all configuration. Create one `Settings` class per deployment context (executor, dispatcher, dashboard) with proper validation and defaults.

---

## 11. LOW: Add Structured Logging

**Problem:** Logging uses plain text format with inconsistent context:
```python
logger.debug("Heartbeat failed", exc_info=True)
logger.info("Matched %s message deliveries", count)
```

**Impact:** Hard to search/filter logs in production. Missing correlation IDs make it difficult to trace a request across components.

**Suggestion:** Use `structlog` or JSON logging with consistent fields:
```python
logger.info("deliveries_matched", count=count, cogent=cogent_name, tick_id=tick_id)
```

---

## 12. LOW: Clean Up String Splitting Without Validation

**Problem:** Several `str.split()` results are indexed without validation:

- `src/cogtainer/update_cli.py:872` — `password = user_pass.split(":", 1)[1]`
- `src/cogtainer/cogtainer_cli.py:445` — `repo = current_image.rsplit(":", 1)[0]`
- `src/cogos/io/discord/bridge.py:446` — `type_suffix = message_type.split(":")[1]`

**Impact:** `IndexError` if the expected delimiter is missing.

**Suggestion:** Use tuple unpacking with validation:
```python
parts = user_pass.split(":", 1)
if len(parts) != 2:
    raise ValueError(f"Invalid auth format: expected 'user:pass'")
_, password = parts
```

---

## Summary — Recommended Priority Order

| # | Improvement | Effort | Impact | Risk Reduction |
|---|------------|--------|--------|----------------|
| 1 | Unify Repository classes | Large | High | Maintainability |
| 2 | Fix silent exception swallowing | Medium | High | Observability |
| 3 | Add HTTP timeouts | Small | High | Reliability |
| 4 | Defensive array access | Small | High | Crash prevention |
| 5 | Eliminate global state | Medium | Medium | Testability |
| 6 | Extract constants | Small | Medium | Maintainability |
| 7 | Exponential backoff | Small | Medium | Reliability |
| 8 | Harden exec() usage | Medium | Medium | Security |
| 9 | Test coverage gaps | Large | Medium | Regression safety |
| 10 | Standardize config | Medium | Medium | Consistency |
| 11 | Structured logging | Medium | Low | Observability |
| 12 | Safe string splitting | Small | Low | Crash prevention |

**Quick wins (small effort, high impact):** Items 3, 4, 6, 7, 12 — could all be done in a single focused session.

**Biggest architectural win:** Item 1 (unify repositories) — reduces ~4,200 lines of duplicated patterns and makes every future DB change easier.
