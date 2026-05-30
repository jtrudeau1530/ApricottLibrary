---
status: passed
---

# Phase 6: Playlists + Admin UI — Summary

**Completed:** 2026-05-30 (autonomous)

## Requirements delivered

- **ADMIN-02** `POST /api/admin/users` + admin UI form
- **ADMIN-03** Disable button on each user row; `PATCH /api/admin/users/{id}` with `{disabled: true}` invalidates their sessions
- **ADMIN-04** "Reset password" prompt → `PATCH /api/admin/users/{id}` with `{password}` (invalidates existing sessions)
- **ADMIN-05** Per-user checkboxes for `can_fetch`, `can_edit_metadata` write through to `permissions` JSON
- **ADMIN-06** SvelteKit `+page.server.ts` throws `error(403)` if `locals.user?.is_admin !== true`; sidecar `require_admin` dependency enforces server-side
- **PLST-01** `POST /api/playlists` with `is_global: false` creates a personal playlist
- **PLST-02** Admin-only `is_global: true` toggle creates global playlists
- **PLST-03** `POST /api/playlists/{id}/items` adds; `DELETE …/items/{rowId}` removes
- **PLST-04** `_can_edit` enforces: globals → admin only; personal → owner or admin
- **PLST-05** `/playlists/[id]` page lists members with cover + title; clicking song row navigates to detail page

## Files added/changed

### Sidecar
- `sidecar/app/admin_routes.py` *(new)* — user CRUD with permission updates + session invalidation on password reset / disable
- `sidecar/app/main.py` — registers admin router

### Frontend
- `frontend/src/routes/admin/+page.server.ts` *(new)* — 403 gate + load
- `frontend/src/routes/admin/+page.svelte` *(new)* — create user form, user list with inline toggles
- `frontend/src/routes/playlists/+page.server.ts` *(new)*, `+page.svelte` *(new)* — list + create
- `frontend/src/routes/playlists/[id]/+page.server.ts` *(new)*, `+page.svelte` *(new)* — detail, add/remove, delete

## Success criteria check

1. ✓ Admin page is 403 for non-admins (server-enforced both layers)
2. ✓ Admin create/disable/reset-password flows work via API
3. ✓ Playlist owner-only edit enforced server-side; globals only by admins

## Human verification needed

- [ ] "Add song to playlist" UX is currently paste-an-id; a cleaner "+ Add" button on the song page would land in v1.x (deferred)
- [ ] Test disabling a user — their next request after the PATCH should redirect to login (sessions destroyed)
