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

  // ---- Paste flow ----
  let pasteText = $state('');
  let pastePreview = $state<{
    found_ids: number;
    resolved_count: number;
    missing_ids: string[];
    queued_count: number;
    library_count: number;
    tracks: PlaylistTrack[];
    error_counts?: Record<string, number>;
  } | null>(null);
  let pasteLoading = $state(false);
  let pasteError = $state<string | null>(null);
  let pasteImporting = $state(false);
  let pasteResult = $state<{
    enqueued: number;
    skipped_queued: number;
    skipped_library: number;
    missing_ids: string[];
    total_found: number;
  } | null>(null);

  async function previewPaste() {
    if (!pasteText.trim()) return;
    pasteLoading = true;
    pasteError = null;
    pastePreview = null;
    pasteResult = null;
    try {
      const res = await fetch('/api/spotify/paste/preview', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: pasteText })
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `Failed (${res.status})` }));
        throw new Error(String(body.detail ?? `Failed (${res.status})`));
      }
      pastePreview = await res.json();
    } catch (e) {
      pasteError = (e as Error).message;
    } finally {
      pasteLoading = false;
    }
  }

  async function importPaste() {
    if (!pastePreview || pastePreview.tracks.length === 0) {
      pasteError = 'Run Preview first.';
      return;
    }
    pasteImporting = true;
    pasteError = null;
    try {
      // Send already-resolved tracks straight to the queue — no re-resolve,
      // no Spotify rate-limit risk for large pastes.
      const tracks = pastePreview.tracks.map((t) => ({
        id: t.id,
        name: t.name,
        artists: t.artists,
        album: t.album,
        cover_url: t.cover_url
      }));
      const res = await fetch('/api/spotify/paste/enqueue', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tracks })
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `Failed (${res.status})` }));
        throw new Error(String(body.detail ?? `Failed (${res.status})`));
      }
      const result = await res.json();
      pasteResult = {
        ...result,
        missing_ids: pastePreview.missing_ids,
        total_found: pastePreview.found_ids
      };
    } catch (e) {
      pasteError = (e as Error).message;
    } finally {
      pasteImporting = false;
    }
  }

  let pasteWillEnqueue = $derived(
    pastePreview ? pastePreview.resolved_count - pastePreview.queued_count - pastePreview.library_count : 0
  );

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
    Pick one of your Spotify playlists below, or paste Spotify track links / exported CSV.
  </p>

  <!-- Paste flow — works even when Spotify denies the playlist tracks endpoint -->
  <section class="rounded-2xl bg-zinc-900 p-5 mb-6">
    <h2 class="font-semibold mb-1">Paste Spotify tracks</h2>
    <p class="text-xs text-zinc-500 mb-3">
      Paste any text — track URLs, URIs, IDs, or CSV from
      <a href="https://watsonbox.github.io/exportify/" target="_blank" rel="noopener" class="text-apricot-400 hover:underline">Exportify</a>,
      Soundiiz, TuneMyMusic, etc. We pull the Spotify track IDs out of it.
    </p>
    <textarea
      bind:value={pasteText}
      placeholder={'https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp\nspotify:track:3n3Ppam7vgaVa1iaRUc9Lp\n…'}
      rows="6"
      class="w-full rounded-lg bg-zinc-800 px-3 py-2 font-mono text-xs"
    ></textarea>

    <div class="mt-3 flex items-center gap-3">
      <button
        type="button"
        onclick={previewPaste}
        disabled={pasteLoading || !pasteText.trim()}
        class="rounded-lg bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5 text-sm disabled:opacity-50"
      >
        {pasteLoading ? 'Scanning…' : 'Preview'}
      </button>
      {#if pastePreview}
        <span class="text-sm text-zinc-400">
          Found {pastePreview.found_ids} ids
          <span class="mx-2 text-zinc-600">·</span>
          <span class="text-apricot-400">{pasteWillEnqueue} new</span>
          <span class="mx-2 text-zinc-600">·</span>
          {pastePreview.library_count} in library
          <span class="mx-2 text-zinc-600">·</span>
          {pastePreview.queued_count} already queued
          {#if pastePreview.missing_ids.length > 0}
            <span class="mx-2 text-zinc-600">·</span>
            <span class="text-red-400">
              {pastePreview.missing_ids.length} unresolved
              {#if pastePreview.error_counts?.['429']}
                (Spotify rate-limited {pastePreview.error_counts['429']} — wait a minute, then Preview again)
              {:else if pastePreview.error_counts && Object.keys(pastePreview.error_counts).length > 0}
                ({Object.entries(pastePreview.error_counts)
                  .map(([k, v]) => `${v}×${k}`)
                  .join(', ')})
              {/if}
            </span>
          {/if}
        </span>
        <button
          type="button"
          onclick={importPaste}
          disabled={pasteImporting || pasteWillEnqueue === 0}
          class="ml-auto rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-4 py-2 disabled:opacity-50"
        >
          {pasteImporting ? 'Importing…' : `Add ${pasteWillEnqueue} to queue`}
        </button>
      {/if}
    </div>

    {#if pasteError}
      <p class="mt-3 text-sm text-red-400">{pasteError}</p>
    {/if}
    {#if pasteResult}
      <div class="mt-3 rounded-lg border border-apricot-500/40 bg-apricot-900/20 px-4 py-3 text-sm">
        <strong>Done.</strong>
        Enqueued {pasteResult.enqueued}, skipped {pasteResult.skipped_library} in library,
        skipped {pasteResult.skipped_queued} already queued
        {#if pasteResult.missing_ids.length > 0}
          ({pasteResult.missing_ids.length} ids couldn't be resolved)
        {/if}.
      </div>
    {/if}

    {#if pastePreview && pastePreview.tracks.length > 0}
      <ul class="mt-4 divide-y divide-zinc-800 rounded-lg bg-zinc-950 max-h-72 overflow-y-auto">
        {#each pastePreview.tracks as t (t.id)}
          <li class="px-4 py-2 flex items-center gap-3">
            {#if t.cover_url}
              <img src={t.cover_url} alt="" class="w-8 h-8 rounded" loading="lazy" />
            {:else}
              <div class="w-8 h-8 rounded bg-zinc-800"></div>
            {/if}
            <div class="flex-1 min-w-0">
              <p class="truncate text-sm">{t.name}</p>
              <p class="truncate text-xs text-zinc-500">{t.artists.join(', ')}</p>
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

  <h2 class="font-semibold mb-3">Or pick a playlist</h2>

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
