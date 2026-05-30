<script lang="ts">
  type Playlist = {
    id: string;
    name: string;
    song_count: number;
    owner_username: string | null;
    cover_url: string | null;
  };
  let { playlists }: { playlists: Playlist[] } = $props();
</script>

<section class="rounded-2xl bg-zinc-900 p-5">
  <h2 class="font-semibold mb-3 flex items-center justify-between">
    Playlists
    <a href="/playlists" class="text-xs text-zinc-400 hover:text-apricot-400">See all →</a>
  </h2>
  {#if playlists.length === 0}
    <p class="text-sm text-zinc-500">No playlists yet.</p>
  {:else}
    <ul class="grid grid-cols-2 gap-3">
      {#each playlists.slice(0, 6) as p (p.id)}
        <li>
          <a href={`/playlists/${p.id}`} class="block rounded-lg bg-zinc-800/60 hover:bg-zinc-800 p-3">
            {#if p.cover_url}
              <img src={p.cover_url} alt="" class="w-full aspect-square rounded mb-2 object-cover" />
            {:else}
              <div class="w-full aspect-square rounded mb-2 bg-zinc-700"></div>
            {/if}
            <p class="truncate text-sm font-medium">{p.name}</p>
            <p class="text-xs text-zinc-500">
              {p.song_count} {p.song_count === 1 ? 'song' : 'songs'}{p.owner_username
                ? ` · ${p.owner_username}`
                : ''}
            </p>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</section>
