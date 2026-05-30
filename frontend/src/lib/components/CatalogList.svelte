<script lang="ts">
  type Track = {
    id: string;
    title: string;
    artist: string;
    album: string;
    duration_seconds: number | null;
    album_art_url: string | null;
    added_at: string | null;
  };

  let { tracks, total }: { tracks: Track[]; total: number } = $props();

  function fmtDuration(s: number | null): string {
    if (!s) return '';
    const m = Math.floor(s / 60);
    const sec = String(Math.floor(s % 60)).padStart(2, '0');
    return `${m}:${sec}`;
  }
</script>

<section class="rounded-2xl bg-zinc-900">
  <header class="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
    <h2 class="font-semibold">Library</h2>
    <span class="text-sm text-zinc-500">{total.toLocaleString()} tracks</span>
  </header>

  <ul class="divide-y divide-zinc-800">
    {#each tracks as t (t.id)}
      <li class="grid grid-cols-[48px_1fr_auto] items-center gap-3 px-5 py-2.5 hover:bg-zinc-800/40">
        {#if t.album_art_url}
          <img src={t.album_art_url} alt="" class="w-12 h-12 rounded object-cover" loading="lazy" />
        {:else}
          <div class="w-12 h-12 rounded bg-zinc-800"></div>
        {/if}
        <a href={`/song/${t.id}`} class="min-w-0 block">
          <p class="truncate font-medium">{t.title}</p>
          <p class="truncate text-sm text-zinc-400">
            {t.artist}{t.album ? ` · ${t.album}` : ''}
          </p>
        </a>
        <span class="text-sm text-zinc-500 tabular-nums">{fmtDuration(t.duration_seconds)}</span>
      </li>
    {/each}
  </ul>

  {#if tracks.length === 0}
    <p class="px-5 py-8 text-center text-zinc-500">
      No songs yet. Use the search above to add your first track.
    </p>
  {/if}
</section>
