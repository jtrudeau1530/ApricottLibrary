<script lang="ts">
  import { invalidateAll } from '$app/navigation';

  type Playlist = {
    id: string;
    name: string;
    owner_id: string | null;
    owner_username: string | null;
    song_count: number;
  };

  let { data } = $props();
  let lists = $derived(data.playlists as Playlist[]);

  let name = $state('');
  let isGlobal = $state(false);
  let creating = $state(false);
  let createError = $state<string | null>(null);

  async function createPlaylist() {
    creating = true;
    createError = null;
    try {
      const res = await fetch('/api/playlists', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, is_global: isGlobal })
      });
      if (!res.ok) {
        if (res.status === 403) throw new Error('Only admins can create global playlists.');
        throw new Error(`Create failed (${res.status})`);
      }
      name = '';
      isGlobal = false;
      await invalidateAll();
    } catch (e) {
      createError = (e as Error).message;
    } finally {
      creating = false;
    }
  }
</script>

<svelte:head>
  <title>Playlists · Apricot Library</title>
</svelte:head>

<main class="min-h-screen p-6 max-w-3xl mx-auto space-y-6">
  <header class="flex items-center justify-between">
    <h1 class="text-2xl font-bold text-apricot-400">Playlists</h1>
    <a href="/" class="text-sm text-zinc-400 hover:text-apricot-400">← Home</a>
  </header>

  <section class="rounded-2xl bg-zinc-900 p-5">
    <h2 class="font-semibold mb-3">Create a playlist</h2>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        createPlaylist();
      }}
      class="flex flex-wrap gap-3"
    >
      <input
        bind:value={name}
        placeholder="Playlist name"
        required
        class="flex-1 min-w-[200px] rounded-lg bg-zinc-800 px-3 py-2"
      />
      {#if data.user?.is_admin}
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" bind:checked={isGlobal} /> Global
        </label>
      {/if}
      <button
        type="submit"
        disabled={creating}
        class="rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-4 py-2 disabled:opacity-50"
      >
        {creating ? 'Creating…' : 'Create'}
      </button>
    </form>
    {#if createError}
      <p class="mt-2 text-sm text-red-400">{createError}</p>
    {/if}
  </section>

  <section class="rounded-2xl bg-zinc-900">
    <ul class="divide-y divide-zinc-800">
      {#each lists as p (p.id)}
        <li class="px-5 py-3 flex items-center gap-4">
          <div class="flex-1 min-w-0">
            <a href={`/playlists/${p.id}`} class="font-medium hover:text-apricot-400 truncate block">
              {p.name}
              {#if p.owner_id === null}
                <span class="ml-2 text-xs px-1.5 py-0.5 rounded bg-apricot-900 text-apricot-200">global</span>
              {/if}
            </a>
            <p class="text-xs text-zinc-500">
              {p.song_count} songs{p.owner_username ? ` · ${p.owner_username}` : ''}
            </p>
          </div>
        </li>
      {:else}
        <li class="px-5 py-8 text-center text-zinc-500">No playlists yet.</li>
      {/each}
    </ul>
  </section>
</main>
