<script lang="ts">
  type Playlist = {
    id: string;
    name: string;
    owner: string;
    track_count: number | null;
    cover_url: string | null;
  };

  function isSpotifyCurated(owner: string): boolean {
    return owner.toLowerCase() === 'spotify';
  }

  type PlaylistTrack = {
    id: string;
    name: string;
    artists: string[];
    album: string;
    cover_url: string | null;
    already_queued: boolean;
    already_in_library: boolean;
  };

  let { data } = $props();
  let playlists = $derived(data.playlists as Playlist[]);
  let loadError = $derived(data.error as string | null);

  let selected = $state<Playlist | null>(null);
  let preview = $state<{
    items: PlaylistTrack[];
    count: number;
    queued_count: number;
    library_count: number;
  } | null>(null);
  let loadingPreview = $state(false);
  let previewError = $state<string | null>(null);

  let importing = $state(false);
  let importResult = $state<{
    enqueued: number;
    skipped_queued: number;
    skipped_library: number;
    total_in_playlist: number;
  } | null>(null);
  let importError = $state<string | null>(null);

  async function selectPlaylist(p: Playlist) {
    selected = p;
    preview = null;
    importResult = null;
    importError = null;
    previewError = null;
    loadingPreview = true;
    try {
      const res = await fetch(`/api/spotify/playlists/${encodeURIComponent(p.id)}/tracks`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `Failed (${res.status})` }));
        throw new Error(String(body.detail ?? `Failed (${res.status})`));
      }
      preview = await res.json();
    } catch (e) {
      previewError = (e as Error).message;
    } finally {
      loadingPreview = false;
    }
  }

  async function importPlaylist() {
    if (!selected) return;
    importing = true;
    importError = null;
    try {
      const res = await fetch(`/api/spotify/playlists/${encodeURIComponent(selected.id)}/import`, {
        method: 'POST'
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `Failed (${res.status})` }));
        throw new Error(String(body.detail ?? `Failed (${res.status})`));
      }
      importResult = await res.json();
    } catch (e) {
      importError = (e as Error).message;
    } finally {
      importing = false;
    }
  }

  let willEnqueue = $derived(
    preview ? preview.count - preview.queued_count - preview.library_count : 0
  );
</script>

<svelte:head>
  <title>Import from Spotify · Apricott Library</title>
</svelte:head>

<main class="min-h-screen p-6 max-w-7xl mx-auto">
  <header class="flex items-center justify-between mb-6">
    <h1 class="font-wordmark text-3xl text-apricot-400 leading-none">Import from Spotify</h1>
    <a href="/" class="text-sm text-zinc-400 hover:text-apricot-400">← Home</a>
  </header>

  <p class="text-sm text-zinc-400 mb-6">
    Pick one of your Spotify playlists; we'll queue any tracks that aren't already in the library or
    fetch queue.
  </p>

  <div class="grid lg:grid-cols-[360px_1fr] gap-6">
    <!-- Playlist list -->
    <aside class="rounded-2xl bg-zinc-900 overflow-hidden">
      <h2 class="px-5 py-3 border-b border-zinc-800 font-semibold flex items-center justify-between">
        Your playlists
        <span class="text-xs text-zinc-500">{data.total}</span>
      </h2>
      {#if loadError}
        <div class="px-5 py-4 text-sm text-red-400 border-b border-zinc-800">
          {loadError}
          <p class="mt-2 text-zinc-400">
            Reconnect Spotify at
            <a href="/api/auth/spotify/login" class="text-apricot-400 underline">/api/auth/spotify/login</a>
            to grant the new playlist-read scope.
          </p>
        </div>
      {/if}
      <ul class="divide-y divide-zinc-800 max-h-[70vh] overflow-y-auto">
        {#each playlists as p (p.id)}
          <li>
            <button
              type="button"
              onclick={() => selectPlaylist(p)}
              class="w-full text-left px-5 py-3 flex items-center gap-3 transition-colors"
              class:bg-zinc-800={selected?.id === p.id}
              class:hover:bg-zinc-800={selected?.id !== p.id}
            >
              {#if p.cover_url}
                <img src={p.cover_url} alt="" class="w-12 h-12 rounded object-cover" loading="lazy" />
              {:else}
                <div class="w-12 h-12 rounded bg-zinc-800"></div>
              {/if}
              <div class="flex-1 min-w-0">
                <p class="truncate font-medium">
                  {p.name}
                  {#if isSpotifyCurated(p.owner)}
                    <span class="ml-2 text-[10px] uppercase tracking-wide text-zinc-500">Spotify · not importable</span>
                  {/if}
                </p>
                <p class="truncate text-xs text-zinc-500">
                  {p.owner}{p.track_count !== null ? ` · ${p.track_count} tracks` : ''}
                </p>
              </div>
            </button>
          </li>
        {:else}
          <li class="px-5 py-8 text-center text-zinc-500 text-sm">
            No playlists. Reconnect at <a href="/api/auth/spotify/login" class="text-apricot-400">/api/auth/spotify/login</a>.
          </li>
        {/each}
      </ul>
    </aside>

    <!-- Selected playlist preview -->
    <section class="rounded-2xl bg-zinc-900 p-5 min-h-[300px]">
      {#if !selected}
        <p class="text-zinc-500 text-sm">Select a playlist on the left to preview its tracks.</p>
      {:else if loadingPreview}
        <p class="text-zinc-500 text-sm">Loading tracks…</p>
      {:else if previewError}
        <p class="text-sm text-red-400">{previewError}</p>
      {:else if preview}
        <header class="flex items-start gap-4 mb-5">
          {#if selected.cover_url}
            <img src={selected.cover_url} alt="" class="w-20 h-20 rounded-lg object-cover" />
          {/if}
          <div class="flex-1">
            <h2 class="text-xl font-semibold">{selected.name}</h2>
            <p class="text-sm text-zinc-400">
              {preview.count} tracks
              <span class="text-zinc-600 mx-2">·</span>
              <span class="text-apricot-400">{willEnqueue} new</span>
              <span class="text-zinc-600 mx-2">·</span>
              {preview.library_count} in library
              <span class="text-zinc-600 mx-2">·</span>
              {preview.queued_count} already queued
            </p>
          </div>
          <button
            type="button"
            onclick={importPlaylist}
            disabled={importing || willEnqueue === 0}
            class="rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-4 py-2 disabled:opacity-50"
            title={willEnqueue === 0 ? 'Nothing new to enqueue' : ''}
          >
            {#if importing}
              Importing…
            {:else if importResult}
              Re-import
            {:else}
              Add {willEnqueue} to queue
            {/if}
          </button>
        </header>

        {#if importResult}
          <div class="mb-5 rounded-lg border border-apricot-500/40 bg-apricot-900/20 px-4 py-3 text-sm">
            <strong>Done.</strong>
            Enqueued {importResult.enqueued}, skipped {importResult.skipped_library} in library,
            skipped {importResult.skipped_queued} already queued.
          </div>
        {/if}

        {#if importError}
          <p class="mb-5 text-sm text-red-400">{importError}</p>
        {/if}

        <ul class="divide-y divide-zinc-800 max-h-[60vh] overflow-y-auto rounded-lg bg-zinc-950">
          {#each preview.items as t (t.id)}
            <li class="px-4 py-2.5 flex items-center gap-3">
              {#if t.cover_url}
                <img src={t.cover_url} alt="" class="w-10 h-10 rounded" loading="lazy" />
              {:else}
                <div class="w-10 h-10 rounded bg-zinc-800"></div>
              {/if}
              <div class="flex-1 min-w-0">
                <p class="truncate text-sm font-medium">{t.name}</p>
                <p class="truncate text-xs text-zinc-500">
                  {t.artists.join(', ')}{t.album ? ` · ${t.album}` : ''}
                </p>
              </div>
              {#if t.already_in_library}
                <span class="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">In library</span>
              {:else if t.already_queued}
                <span class="text-xs px-2 py-0.5 rounded bg-apricot-900 text-apricot-200">Queued</span>
              {:else}
                <span class="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-500">New</span>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>
</main>
