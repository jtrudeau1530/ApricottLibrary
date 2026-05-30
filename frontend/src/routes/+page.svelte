<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import SearchBox from '$lib/components/SearchBox.svelte';
  import CatalogList from '$lib/components/CatalogList.svelte';
  import QueueWidget from '$lib/components/QueueWidget.svelte';
  import StorageWidget from '$lib/components/StorageWidget.svelte';
  import PlaylistStrip from '$lib/components/PlaylistStrip.svelte';
  import { startSse, stopSse, seedQueue, queueCount } from '$lib/stores/sse';

  let { data } = $props();

  onMount(() => {
    seedQueue(data.queue as never);
    startSse();
  });
  onDestroy(() => stopSse());
</script>

<svelte:head>
  <title>Apricott Library</title>
</svelte:head>

<main class="min-h-screen">
  <header class="border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <h1 class="font-wordmark text-3xl text-apricot-400 leading-none">Apricott Library</h1>
      {#if $queueCount > 0}
        <span class="text-xs px-2 py-0.5 rounded-full bg-apricot-900 text-apricot-200">
          {$queueCount} queued
        </span>
      {/if}
    </div>
    <div class="flex items-center gap-3 text-sm">
      <a href="/playlists" class="text-zinc-400 hover:text-zinc-100">Playlists</a>
      <a href="/import" class="text-zinc-400 hover:text-zinc-100">Import</a>
      <span class="text-zinc-500">·</span>
      <a
        href={data.user?.is_admin ? '/admin' : undefined}
        class="text-zinc-400 hover:text-zinc-100"
        title={data.user?.is_admin ? 'Open admin' : ''}
      >
        {data.user?.username}
      </a>
      <form method="post" action="/logout">
        <button type="submit" class="rounded-lg bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5">
          Sign out
        </button>
      </form>
    </div>
  </header>

  <div class="grid lg:grid-cols-[1fr_320px] gap-6 px-6 py-6 max-w-screen-2xl mx-auto">
    <div class="space-y-6">
      <SearchBox />
      <CatalogList tracks={(data.tracks as { items: never[] }).items} total={(data.tracks as { total: number }).total} />
    </div>
    <aside class="space-y-6">
      <QueueWidget />
      <StorageWidget initial={data.storage} />
      <PlaylistStrip playlists={data.playlists as never} />
    </aside>
  </div>
</main>
