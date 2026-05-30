<script lang="ts">
  import { storage } from '$lib/stores/sse';

  let { initial }: { initial: { total_bytes: number; used_bytes: number; percent_used: number } | null } =
    $props();

  function fmtBytes(n: number): string {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i += 1;
    }
    return `${v.toFixed(1)} ${units[i]}`;
  }

  let view = $derived($storage ?? initial);
</script>

<section class="rounded-2xl bg-zinc-900 p-5">
  <h2 class="font-semibold mb-3">Storage</h2>
  {#if view}
    <div class="text-sm text-zinc-400 mb-1">
      {fmtBytes(view.used_bytes)} of {fmtBytes(view.total_bytes)} used
    </div>
    <div class="h-2 rounded bg-zinc-800 overflow-hidden">
      <div
        class="h-full"
        class:bg-apricot-500={view.percent_used < 85}
        class:bg-red-500={view.percent_used >= 85}
        style="width: {Math.min(view.percent_used, 100)}%"
      ></div>
    </div>
    <p class="mt-1 text-xs text-zinc-500">{view.percent_used.toFixed(1)}% full</p>
  {:else}
    <p class="text-sm text-zinc-500">Storage stats unavailable.</p>
  {/if}
</section>
