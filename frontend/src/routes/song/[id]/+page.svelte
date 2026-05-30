<script lang="ts">
  let { data } = $props();
  let view = $derived(data.view);
  let track = $derived(view.track);
  let album = $derived(view.album);
  let artist = $derived(view.artist);

  let editing = $state(false);
  let saving = $state(false);
  let form = $state({
    title: track.title,
    artist: track.artist,
    album: album.name,
    description: track.description
  });
  let saveError = $state<string | null>(null);

  function fmtSecondsShort(s: number | null): string {
    if (!s) return '—';
    const m = Math.floor(s / 60);
    const sec = String(Math.floor(s % 60)).padStart(2, '0');
    return `${m}:${sec}`;
  }

  function fmtRuntime(s: number | null): string {
    if (!s) return '—';
    const totalMin = Math.round(s / 60);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  async function save() {
    saving = true;
    saveError = null;
    try {
      const res = await fetch(`/api/catalog/tracks/${encodeURIComponent(track.id)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(form)
      });
      if (!res.ok) {
        if (res.status === 403) throw new Error('You do not have edit-metadata permission.');
        throw new Error(`Update failed (${res.status})`);
      }
      editing = false;
      location.reload();
    } catch (e) {
      saveError = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>{track.title} · Apricott Library</title>
</svelte:head>

<main class="min-h-screen relative">
  <!-- Hero / backdrop -->
  <div class="relative h-[55vh] min-h-[420px] w-full overflow-hidden">
    {#if artist.backdrop_url}
      <img
        src={artist.backdrop_url}
        alt=""
        class="absolute inset-0 w-full h-full object-cover"
      />
    {:else}
      <div class="absolute inset-0 bg-gradient-to-br from-zinc-900 to-zinc-950"></div>
    {/if}
    <div
      class="absolute inset-0 bg-gradient-to-t from-zinc-950 via-zinc-950/60 to-transparent"
    ></div>

    <a
      href="/"
      class="absolute top-5 left-5 z-10 rounded-full bg-black/40 hover:bg-black/60 backdrop-blur px-3 py-1.5 text-sm"
    >
      ← Back
    </a>

    {#if artist.logo_url}
      <img
        src={artist.logo_url}
        alt={artist.name}
        class="absolute top-1/2 right-12 -translate-y-1/2 max-h-48 max-w-md drop-shadow-2xl"
      />
    {/if}
  </div>

  <!-- Album cover + info -->
  <section
    class="relative -mt-40 px-6 lg:px-12 grid lg:grid-cols-[320px_1fr] gap-8 max-w-7xl mx-auto"
  >
    <div class="rounded-2xl overflow-hidden shadow-2xl bg-zinc-900 aspect-square">
      {#if album.cover_url}
        <img src={album.cover_url} alt="" class="w-full h-full object-cover" />
      {:else}
        <div class="w-full h-full grid place-items-center text-zinc-500 text-sm">No cover</div>
      {/if}
    </div>

    <div class="space-y-4 self-end pb-2">
      <header>
        <h1 class="text-4xl font-semibold leading-tight">{album.name}</h1>
        <p class="text-lg text-zinc-300">{artist.name}</p>
        <p class="text-sm text-zinc-400 mt-1 tracking-wide">
          {album.track_count}
          {album.track_count === 1 ? 'track' : 'tracks'}
          <span class="mx-2 text-zinc-600">·</span>
          {fmtRuntime(album.duration_seconds)}
          {#if album.year}
            <span class="mx-2 text-zinc-600">·</span>
            {album.year}
          {/if}
        </p>
      </header>

      <audio controls preload="metadata" class="w-full max-w-xl">
        <source src={`/api/audio/${track.id}/stream`} />
        Your browser does not support audio playback.
      </audio>

      {#if view.tags.length > 0}
        <p class="text-sm text-zinc-300">
          {#each view.tags as t, i (t)}
            <span class="font-semibold">{t}</span>{#if i < view.tags.length - 1}<span class="text-zinc-500">, </span>{/if}
          {/each}
        </p>
      {/if}

      {#if view.genres.length > 0}
        <div class="flex items-baseline gap-4 text-sm">
          <span class="text-zinc-500">Genre</span>
          <span class="font-semibold">{view.genres.join(', ')}</span>
        </div>
      {/if}

      <button
        type="button"
        onclick={() => (editing = !editing)}
        class="text-sm rounded-lg bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5"
      >
        {editing ? 'Cancel' : 'Edit metadata'}
      </button>
    </div>
  </section>

  <!-- Track listing -->
  <section class="px-6 lg:px-12 mt-10 max-w-7xl mx-auto">
    <ul class="rounded-2xl overflow-hidden divide-y divide-zinc-900">
      {#each view.siblings as t (t.id)}
        <li
          class="grid grid-cols-[40px_1fr_auto] items-center gap-4 px-5 py-3 transition-colors"
          class:bg-zinc-900={t.is_current}
          class:hover:bg-zinc-900={!t.is_current}
        >
          <span class="text-sm text-zinc-500 tabular-nums">
            {t.index ?? ''}
          </span>
          {#if t.is_current}
            <span class="truncate text-apricot-400 font-medium">{t.title}</span>
          {:else}
            <a href={`/song/${t.id}`} class="truncate hover:text-apricot-400">{t.title}</a>
          {/if}
          <span class="text-sm text-zinc-500 tabular-nums">{fmtSecondsShort(t.duration_seconds)}</span>
        </li>
      {/each}
    </ul>

    {#if album.description}
      <p class="mt-8 text-sm text-zinc-300 whitespace-pre-wrap max-w-3xl">{album.description}</p>
    {/if}
  </section>

  {#if editing}
    <section class="px-6 lg:px-12 mt-10 max-w-2xl mx-auto pb-12">
      <form
        onsubmit={(e) => {
          e.preventDefault();
          save();
        }}
        class="space-y-3 rounded-2xl bg-zinc-900 p-5"
      >
        <h2 class="font-semibold">Edit this track</h2>
        <label class="block">
          <span class="block text-sm text-zinc-400 mb-1">Title</span>
          <input bind:value={form.title} class="w-full rounded-lg bg-zinc-800 px-3 py-2" />
        </label>
        <label class="block">
          <span class="block text-sm text-zinc-400 mb-1">Artist</span>
          <input bind:value={form.artist} class="w-full rounded-lg bg-zinc-800 px-3 py-2" />
        </label>
        <label class="block">
          <span class="block text-sm text-zinc-400 mb-1">Album</span>
          <input bind:value={form.album} class="w-full rounded-lg bg-zinc-800 px-3 py-2" />
        </label>
        <label class="block">
          <span class="block text-sm text-zinc-400 mb-1">Description</span>
          <textarea
            bind:value={form.description}
            rows="3"
            class="w-full rounded-lg bg-zinc-800 px-3 py-2"
          ></textarea>
        </label>
        {#if saveError}
          <p class="text-sm text-red-400">{saveError}</p>
        {/if}
        <button
          type="submit"
          disabled={saving}
          class="rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-4 py-2 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </form>
    </section>
  {/if}

  <div class="pb-12"></div>
</main>
