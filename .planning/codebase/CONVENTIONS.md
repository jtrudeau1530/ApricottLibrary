# Coding Conventions

**Analysis Date:** 2026-05-29

## Naming Patterns

**Files:**
- Module files use lowercase with underscores: `config.py`, `librespot_session.py`, `spotify.py`
- No hyphens in filenames; underscores are preferred
- Descriptive names reflecting module responsibility

**Functions:**
- Lowercase with underscores (snake_case) for all functions
- Public functions: no leading underscore (e.g., `search_tracks()`, `download_track()`)
- Private/internal functions: leading underscore (e.g., `_safe()`, `_get_token()`, `_prune_states()`)
- Async functions use `async def` keyword; names don't indicate async status
- Example: `async def search_tracks()` at `sidecar/app/spotify.py:40`

**Variables:**
- Snake_case for local variables and module-level state
- Private module state uses leading underscore: `_session`, `_token`, `_pending_states`
- Configuration singleton: all caps for module-level constants (`VALID_TRACK_ID`, `AUTH_URL`, `SCOPES`, `STATE_TTL_SECONDS`)
- Type hints used throughout, especially for function parameters and returns

**Types:**
- Pydantic `BaseSettings` for configuration classes: `Settings` at `sidecar/app/config.py:4`
- Custom data transformation functions return plain dicts (not dataclasses): `_to_track()` returns `dict` at `sidecar/app/spotify.py:63`
- Type unions use pipe syntax: `str | None` at `sidecar/app/config.py:34`

## Code Style

**Formatting:**
- No explicit formatter configured (no `.eslintrc`, `.prettierrc`, `ruff.toml`, or `pyproject.toml`)
- Inferred style from codebase:
  - 4-space indentation (Python standard)
  - 100-character line length (mostly adhered to; some lines exceed this)
  - Imports at top of file, blank line before code
  - 2 blank lines between top-level function/class definitions
  - Single blank line between method definitions

**Linting:**
- No linting configuration file found
- Code follows PEP 8 conventions implicitly
- Import organization follows Python conventions (stdlib, third-party, local)

## Import Organization

**Order:**
1. Standard library imports (e.g., `asyncio`, `json`, `logging`, `pathlib`, `time`)
2. Third-party imports (e.g., `fastapi`, `httpx`, `pydantic_settings`)
3. Local application imports (relative imports from `.` or `..`)

**Path Aliases:**
- None detected; relative imports used exclusively
- Example: `from . import librespot_session` at `sidecar/app/main.py:7`
- Example: `from .config import settings` at `sidecar/app/spotify.py:6`

**Patterns:**
- Relative imports within same package (`.module`)
- Function imports alongside module imports: `from .auth import librespot_router, router as auth_router` at `sidecar/app/main.py:8-9`
- Import renamed for clarity: `router as auth_router`

## Error Handling

**Patterns:**
- FastAPI `HTTPException` used for API responses
  - Status code provided explicitly: `HTTPException(503, "message")`
  - Named parameter `detail=` or positional arguments both used
  - Example: `raise HTTPException(401, "Spotify account not connected...")` at `sidecar/app/auth.py:148`
- Try/except blocks catch specific exceptions:
  - `ConnectionRefusedError, ConnectionError, OSError` caught with logging at `sidecar/app/librespot_session.py:71`
  - General `Exception` catch with message formatting: `except Exception as e:` at `sidecar/app/auth.py:138`
- HTTP response status checks: `if resp.status_code != 200:` at `sidecar/app/auth.py:94`
- Return `None` for missing resources: `if resp.status_code == 404: return None` at `sidecar/app/spotify.py:57`

## Logging

**Framework:** Python built-in `logging` module

**Patterns:**
- Module-level logger created per file: `log = logging.getLogger("librespot_session")` at `sidecar/app/librespot_session.py:12`
- Logging used for operational events (retries, warnings):
  - `log.warning()` for transient failures: `log.warning("librespot session attempt %d failed: %s", attempt, e)` at `sidecar/app/librespot_session.py:73`
  - `log.info()` for recovery: `log.info("librespot session ok on attempt %d", attempt)` at `sidecar/app/librespot_session.py:69`
- Structured logging with %-formatting: `log.warning("message %s", variable)`

## Comments

**When to Comment:**
- Function docstrings describe purpose and notable behavior
- Example: `"""Return a valid user access token, refreshing if expired. Used by /download."""` at `sidecar/app/auth.py:145`
- Inline comments explain algorithm or external API specifics (e.g., `VALID_TRACK_ID` regex, OAuth flow details)
- Inline comments for non-obvious logic: `# Keep within 30s of expiry threshold before refreshing` (implicit in code at `sidecar/app/spotify.py:20`)

**JSDoc/TSDoc:**
- Not applicable; Python codebase uses docstrings instead

**Docstring Style:**
- Function docstrings use triple-quoted strings
- Brief one-line descriptions followed by optional detail
- Example: `"""Stream a track via librespot and write OGG Vorbis bytes to output_path. Sync; run via to_thread."""` at `sidecar/app/librespot_session.py:84`

## Function Design

**Size:**
- Functions kept relatively small (10-50 lines typical)
- Single responsibility: `_get_token()` handles token acquisition/refresh only
- Async operations broken into logical steps (e.g., `async def callback()` receives state parameter at `sidecar/app/auth.py:69`)

**Parameters:**
- Type hints on all parameters: `async def search(q: str = Query(...), limit: int = Query(20, ge=1, le=50))` at `sidecar/app/main.py:30-31`
- FastAPI Query/Path/Request dependencies used for route parameters
- Optional parameters use defaults: `limit: int = 20` at `sidecar/app/spotify.py:40`

**Return Values:**
- Type hints on all return values: `-> dict`, `-> str | None`, `-> Path`
- Async functions explicitly typed: `async def search_tracks(...) -> list[dict]:` at `sidecar/app/spotify.py:40`
- None used for missing/error cases: `-> dict | None` at `sidecar/app/spotify.py:51`

## Module Design

**Exports:**
- Module-level singleton instances exported: `spotify = SpotifyClient()` at `sidecar/app/spotify.py:79`
- Module-level singleton configuration: `settings = Settings()` at `sidecar/app/config.py:16`
- Routers instantiated and included in app: `app.include_router(auth_router)` at `sidecar/app/main.py:14`

**Barrel Files:**
- Empty `__init__.py` files used: `sidecar/app/__init__.py` is blank
- No barrel file exports; submodules imported directly where needed

**Private Modules:**
- Modules with leading underscore don't exist; "private" functions use underscore prefix instead
- Helper functions like `_safe()`, `_to_track()`, `_get_token()` private within their modules

## Async/Concurrency Patterns

**Async Functions:**
- FastAPI endpoints are async: `async def search()` at `sidecar/app/main.py:30`
- Blocking operations delegated to thread pool: `await asyncio.to_thread(librespot_session.download_track, ...)` at `sidecar/app/main.py:49`
- Synchronous modules (e.g., librespot_session) designed to be callable from threads

**Locking:**
- Threading locks used for session state: `_session_lock = Lock()` at `sidecar/app/librespot_session.py:14`
- Global mutable state protected: `with _session_lock:` at `sidecar/app/librespot_session.py:54`

## Configuration Management

**Settings Pattern:**
- Pydantic `BaseSettings` class in `sidecar/app/config.py`
- Environment variables loaded automatically from `.env`
- Model config: `SettingsConfigDict(env_file=".env", extra="ignore")`
- Defaults provided for all settings
- Singleton instance: `settings = Settings()` instantiated once per app

**Environment Loading:**
- Configuration read from environment at app startup
- Example: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `MEDIA_PATH`, `DATA_PATH` at `sidecar/app/config.py:7-13`

---

*Convention analysis: 2026-05-29*
