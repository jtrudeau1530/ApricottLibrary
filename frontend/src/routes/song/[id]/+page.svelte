<script lang="ts">
  let { data } = $props();
  let { track } = $derived(data);

  let editing = $state(false);
  let saving = $state(false);
  let form = $state({
    title: track.title,
    artist: track.artist,
    album: track.album,
    description: track.description
  });
  let saveError = $state<string | null>(null);

  function fmt(s: number | null): string {
    if (!s) return '—';
    const m = Math.floor(s / 60);
    const sec = String(Math.floor(s % 60)).padStart(2, '0');
    return `${m}:${sec}`;
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
      // Optimistic local update — Jellyfin scan + Postgres are authoritative.
      track = { ...track, ...form };
      editing = false;
    } catch (e) {
      saveError = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>{track.title} · Apricot Library</title>
</svelte:head>

<main class="min-h-screen p-6">
  <a href="/" class="text-sm text-zinc-400 hover:text-apricot-400">← Back to library</a>

  <article class="mt-6 grid md:grid-cols-[300px_1fr] gap-8 max-w-5xl mx-auto">
    {#if track.album_art_url}
      <img src={track.album_art_url} alt="" class="w-full rounded-2xl shadow-xl" />
    {:else}
      <div class="w-full aspect-square rounded-2xl bg-zinc-800"></div>
    {/if}

    <div class="space-y-5">
      <header>
        <h1 class="text-3xl font-bold">{track.title}</h1>
        <p class="text-lg text-zinc-300">{track.artist}</p>
        <p class="text-sm text-zinc-500">
          {track.album || 'Unknown album'} · {fmt(track.duration_seconds)}
        </p>
      </header>

      <audio controls preload="metadata" class="w-full">
        <source src={`/api/audio/${track.id}/stream`} />
        Your browser does not support audio playback.
      </audio>

      {#if track.description}
        <p class="text-sm text-zinc-300 whitespace-pre-wrap">{track.description}</p>
      {/if}

      <button
        type="button"
        onclick={() => (editing = !editing)}
        class="rounded-lg bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5 text-sm"
      >
        {editing ? 'Cancel' : 'Edit metadata'}
      </button>

      {#if editing}
        <form
          onsubmit={(e) => {
            e.preventDefault();
            save();
          }}
          class="space-y-3 rounded-2xl bg-zinc-900 p-5"
        >
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
      {/if}
    </div>
  </article>
</main>
