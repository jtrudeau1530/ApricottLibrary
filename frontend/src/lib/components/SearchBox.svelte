<script lang="ts">
  import { onDestroy } from 'svelte';
  import { queuedTrackIds } from '$lib/stores/sse';

  type SpotifyResult = {
    id: string;
    name: string;
    artists: string[];
    album: string;
    cover_url: string | null;
  };

  let query = $state('');
  let results = $state<SpotifyResult[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let inLibrary = $state<Set<string>>(new Set());
  let queuing = $state<Record<string, 'queuing' | 'queued' | 'error'>>({});

  let controller: AbortController | null = null;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
    const q = query.trim();
    if (!q || q.length < 2) {
      results = [];
      loading = false;
      return;
    }
    debounceTimer = setTimeout(() => doSearch(q), 300);
  });

  async function doSearch(q: string) {
    if (controller) controller.abort();
    controller = new AbortController();
    loading = true;
    error = null;
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`, {
        signal: controller.signal
      });
      if (!res.ok) {
        let detail = `Search failed (${res.status})`;
        try {
          const body = await res.json();
          if (body?.detail) detail = String(body.detail);
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const body = await res.json();
      results = (body.tracks || []) as SpotifyResult[];
    } catch (e: unknown) {
      if ((e as { name?: string }).name === 'AbortError') return;
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function addToQueue(track: SpotifyResult) {
    queuing[track.id] = 'queuing';
    try {
      const res = await fetch('/api/queue', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          spotify_track_id: track.id,
          track_name: track.name,
          artist_name: track.artists[0] || 'Unknown',
          album_name: track.album || '',
          cover_url: track.cover_url
        })
      });
      if (res.status === 409) {
        queuing[track.id] = 'queued';
        return;
      }
      if (!res.ok) throw new Error(`Enqueue failed (${res.status})`);
      queuing[track.id] = 'queued';
    } catch (e) {
      queuing[track.id] = 'error';
      console.error(e);
    }
  }

  onDestroy(() => {
    controller?.abort();
    if (debounceTimer) clearTimeout(debounceTimer);
  });
</script>

<div class="space-y-3">
  <input
    type="search"
    bind:value={query}
    placeholder="Search Spotify for a song to add…"
    class="w-full rounded-xl bg-zinc-900 px-4 py-3 outline-none focus:ring-2 focus:ring-apricot-500"
  />

  {#if loading}
    <p class="text-sm text-zinc-500">Searching…</p>
  {/if}
  {#if error}
    <p class="text-sm text-red-400">{error}</p>
  {/if}

  {#if results.length > 0}
    <ul class="divide-y divide-zinc-800 rounded-xl bg-zinc-900 overflow-hidden">
      {#each results as track (track.id)}
        {@const alreadyQueued = $queuedTrackIds.has(track.id) || queuing[track.id] === 'queued'}
        {@const isLibrary = inLibrary.has(track.id)}
        <li class="flex items-center gap-3 px-4 py-3">
          {#if track.cover_url}
            <img src={track.cover_url} alt="" class="w-12 h-12 rounded object-cover" loading="lazy" />
          {:else}
            <div class="w-12 h-12 rounded bg-zinc-800"></div>
          {/if}
          <div class="flex-1 min-w-0">
            <p class="truncate font-medium">{track.name}</p>
            <p class="truncate text-sm text-zinc-400">
              {track.artists.join(', ')}{track.album ? ` · ${track.album}` : ''}
            </p>
          </div>
          {#if isLibrary}
            <span class="text-xs px-2 py-1 rounded bg-zinc-800 text-zinc-400">In library</span>
          {:else if alreadyQueued}
            <span class="text-xs px-2 py-1 rounded bg-apricot-900 text-apricot-200">Queued</span>
          {:else}
            <button
              type="button"
              onclick={() => addToQueue(track)}
              disabled={queuing[track.id] === 'queuing'}
              class="text-sm rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-3 py-1.5 disabled:opacity-50"
            >
              {queuing[track.id] === 'queuing' ? 'Adding…' : 'Add'}
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>
