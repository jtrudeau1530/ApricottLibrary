<script lang="ts">
  import { queueItems } from '$lib/stores/sse';
</script>

<section class="rounded-2xl bg-zinc-900 p-5">
  <h2 class="font-semibold mb-3 flex items-center justify-between">
    Queue
    <span class="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300">{$queueItems.length}</span>
  </h2>

  {#if $queueItems.length === 0}
    <p class="text-sm text-zinc-500">Nothing queued. Search above to add tracks.</p>
  {:else}
    <ul class="space-y-3">
      {#each $queueItems as it (it.id)}
        <li class="space-y-1.5">
          <div class="flex items-center gap-2">
            {#if it.cover_url}
              <img src={it.cover_url} alt="" class="w-8 h-8 rounded object-cover" loading="lazy" />
            {/if}
            <div class="flex-1 min-w-0">
              <p class="truncate text-sm font-medium">{it.track_name}</p>
              <p class="truncate text-xs text-zinc-400">{it.artist_name}</p>
            </div>
            {#if it.status === 'running'}
              <span class="text-xs text-apricot-400">{it.progress}%</span>
            {:else if it.status === 'failed'}
              <span class="text-xs text-red-400">Failed</span>
            {:else}
              <span class="text-xs text-zinc-500">Queued</span>
            {/if}
          </div>

          {#if it.status === 'running'}
            <div class="h-1 rounded bg-zinc-800 overflow-hidden">
              <div class="h-full bg-apricot-500" style="width: {it.progress}%"></div>
            </div>
          {/if}

          {#if it.error_message}
            <p class="text-xs text-red-400" title={it.error_message}>{it.error_message}</p>
          {/if}

          {#if it.requester_username}
            <p class="text-[10px] uppercase tracking-wider text-zinc-500">by {it.requester_username}</p>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
