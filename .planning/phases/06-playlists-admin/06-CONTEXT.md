# Phase 6: Playlists + Admin UI - Context

<domain>
- Admin can create users, disable, reset password, set permission flags.
- All users can create/manage their own playlists; admins can create global playlists.
- Playlists page lists all visible playlists; each playlist has a detail page.
</domain>

<decisions>
- Sidecar gains an admin module `admin_routes.py` for user CRUD (admin-only).
- Permissions UI uses two checkboxes: `can_fetch`, `can_edit_metadata`. `is_admin` is set with a separate confirm step (only the master admin can grant admin).
- Playlist CRUD already exists (Phase 4 — added preemptively); Phase 6 builds the UI.
- The 403 check on `/admin` is handled in `hooks.server.ts`.
</decisions>

<deferred>
- Playlist cover art (use first song's art) — Phase 6.x cosmetic follow-up.
</deferred>
