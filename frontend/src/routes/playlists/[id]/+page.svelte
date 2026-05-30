<script lang="ts">
  import { invalidateAll } from '$app/navigation';

  let { data } = $props();
  let { playlist, tracks } = $derived(data);

  let addingId = $state('');
  let addError = $state<string | null>(null);

  async function addItem() {
    if (!addingId.trim()) return;
    addError = null;
    const res = await fetch(`/api/playlists/${encodeURIComponent(playlist.id)}/items`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jellyfin_item_id: addingId.trim() })
    });
    if (!res.ok) {
      addError = res.status === 409 ? 'Already in playlist.' : `Failed (${res.status})`;
      return;
    }
    addingId = '';
    await invalidateAll();
  }

  async function removeItem(rowId: string) {
    await fetch(
      `/api/playlists/${encodeURIComponent(playlist.id)}/items/${encodeURIComponent(rowId)}`,
      { method: 'DELETE' }
    );
    await invalidateAll();
  }

  async function deletePlaylist() {
    if (!confirm(`Delete playlist "${playlist.name}"?`)) return;
    await fetch(`/api/playlists/${encodeURIComponent(playlist.id)}`, { method: 'DELETE' });
    location.href = '/playlists';
  }
</script>

<svelte:head>
  <title>{playlist.name} · Playlists · Apricot Library</title>
</svelte:head>

<main class="min-h-screen p-6 max-w-3xl mx-auto space-y-6">
  <header class="flex items-center justify-between">
    <div>
      <a href="/playlists" class="text-sm text-zinc-400 hover:text-apricot-400">← Playlists</a>
      <h1 class="text-2xl font-bold mt-1">{playlist.name}</h1>
      {#if playlist.is_global}
        <span class="text-xs px-1.5 py-0.5 rounded bg-apricot-900 text-apricot-200">global</span>
      {/if}
    </div>
    <button
      type="button"
      onclick={deletePlaylist}
      class="text-sm rounded-lg bg-red-900 hover:bg-red-800 px-3 py-1.5"
    >
      Delete playlist
    </button>
  </header>

  <section class="rounded-2xl bg-zinc-900 p-5 space-y-3">
    <h2 class="font-semibold">Add a song by Jellyfin item id</h2>
    <p class="text-xs text-zinc-500">
      Browse the library, copy a song's id from its URL (`/song/&lt;id&gt;`), and paste it here. A
      better add-to-playlist flow lands in v1.x.
    </p>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        addItem();
      }}
      class="flex gap-2"
    >
      <input
        bind:value={addingId}
        placeholder="Jellyfin item id"
        class="flex-1 rounded-lg bg-zinc-800 px-3 py-2 font-mono text-sm"
      />
      <button
        type="submit"
        class="rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-4 py-2"
      >
        Add
      </button>
    </form>
    {#if addError}
      <p class="text-sm text-red-400">{addError}</p>
    {/if}
  </section>

  <section class="rounded-2xl bg-zinc-900">
    <ul class="divide-y divide-zinc-800">
      {#each tracks as t (t.row_id)}
        <li class="px-5 py-3 flex items-center gap-3">
          {#if t.track?.album_art_url}
            <img src={t.track.album_art_url} alt="" class="w-10 h-10 rounded" loading="lazy" />
          {/if}
          <a href={`/song/${t.track?.id ?? ''}`} class="flex-1 min-w-0 hover:text-apricot-400">
            <p class="truncate font-medium">{t.track?.title ?? '(unknown)'}</p>
            <p class="truncate text-sm text-zinc-400">{t.track?.artist ?? ''}</p>
          </a>
          <button
            type="button"
            onclick={() => removeItem(t.row_id)}
            class="text-xs rounded bg-zinc-800 hover:bg-zinc-700 px-2 py-1"
          >
            Remove
          </button>
        </li>
      {:else}
        <li class="px-5 py-8 text-center text-zinc-500">No songs in this playlist.</li>
      {/each}
    </ul>
  </section>
</main>
