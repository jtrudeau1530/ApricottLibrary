# Phase 4: Home + Search + Fetch UI - Context

**Gathered:** 2026-05-30 (autonomous)

<domain>
Build the user-facing home page: virtualized song list, Spotify search box with live results, fetch queue widget, storage widget, and live updates over SSE.
</domain>

<decisions>
- Layout: single page (`/`), top header with username + sign-out, right rail with queue + storage, main column with search box + catalog list.
- Search uses 300ms debounce, in-flight abort via `AbortController`.
- "Add to queue" is optimistic: button enters 'queued' state immediately; SSE `queue:added` reconciles + on rejection (409) the button reverts and shows "Already in queue".
- SSE store (`$lib/stores/sse.ts`) opens one `EventSource` on mount, exposes a Svelte 5 reactive store. Tracks current queue items, last storage update, error state.
- Catalog list uses `@humanspeak/svelte-virtual-list`; rows are 64px high; cover art lazy via `loading="lazy"`.
- Frontend never calls Jellyfin directly — only `/api/catalog/*` and `/api/audio/*`.
- For server-side rendering of the initial catalog page, `+page.server.ts` calls the sidecar with the forwarded cookie.
</decisions>

<code_context>
- Phase 2 events: queue:added/running/progress/complete/error/retry + storage:update + queue:hello.
- Phase 3 endpoints: /api/catalog/tracks, /api/catalog/cover/{id}, /api/storage.
- Phase 1+2: /api/queue (POST/GET), /api/search.
</code_context>

<specifics>
- Header style: apricot accent on title; subtle dark zinc panels (per app.css palette).
- Queue badge in nav: count of queued+running rows.
</specifics>

<deferred>
- Drag reorder (v2).
- Search-within-library (Q2-03, v2).
</deferred>
