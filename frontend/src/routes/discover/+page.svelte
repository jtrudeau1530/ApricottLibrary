<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type {
    DiscoveryJob,
    DiscoveryConfiguration,
    DiscoveryTrack,
  } from "$lib/discovery-types";

  let { data } = $props();
  let jobs = $state<DiscoveryJob[]>(untrack(() => data.jobs));
  let configuration = $state<DiscoveryConfiguration | null>(
    untrack(() => data.configuration),
  );
  let selectedId = $state<string | null>(
    untrack(() => data.jobs[0]?.id ?? null),
  );
  let selected = $derived(jobs.find((job) => job.id === selectedId));
  let prompt = $state("");
  let count = $state(20);
  let submitting = $state(false);
  let retrying = $state(false);
  let error = $state<string | null>(untrack(() => data.error));
  let pollError = $state<string | null>(null);
  type Provider = { provider: string; ready: boolean; capability?: string; message?: string };
  type Schedule = { query: string; count: number; interval_hours: number; max_runs: number; runs: number; enabled: boolean; next_run_at: string; last_error?: string };
  let providers = $state<Provider[]>([]);
  let schedule = $state<Schedule | null>(null);
  let scheduleQuery = $state("");
  let scheduleCount = $state(20);
  let scheduleHours = $state(24);
  let scheduleRuns = $state(30);
  let scheduleEnabled = $state(false);
  let scheduleSaving = $state(false);
  let scheduleInitialized = false;
  let minHours = $state(24);
  let maxRuns = $state(30);
  async function loadProviders() {
    try { providers = (await requestJSON<{ items: Provider[] }>("/api/discovery/providers")).items; }
    catch (e) { error = `Readiness check failed: ${(e as Error).message}`; }
  }
  async function saveSchedule(event: SubmitEvent) {
    event.preventDefault(); scheduleSaving = true; error = null;
    try {
      const result = await requestJSON<{ schedule: Schedule }>("/api/discovery/schedule", {
        method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({query:scheduleQuery,count:scheduleCount,interval_hours:scheduleHours,max_runs:scheduleRuns,enabled:scheduleEnabled})
      });
      schedule = result.schedule;
    } catch (e) { error = (e as Error).message; }
    finally { scheduleSaving = false; }
  }
  const terminal = new Set(["ready", "partial", "failed", "sync_failed"]);
  const labels: Record<string, string> = {
    queued: "Waiting to start",
    planning: "Finding songs and checking your library",
    acquiring: "Acquiring and importing music",
    syncing: "Finishing legacy acquisition",
    ready: "Ready",
    partial: "Ready with missing tracks",
    failed: "Needs attention",
    sync_failed: "Legacy acquisition needs attention",
  };

  async function requestJSON<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(path, init);
    const body = await response.json();
    if (!response.ok) {
      const detail = body.detail;
      throw new Error(
        Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join("; ")
          : String(detail ?? `Request failed (${response.status})`),
      );
    }
    return body as T;
  }

  onMount(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    void loadProviders();
    async function poll() {
      try {
        const [result, config, campaign] = await Promise.all([
          requestJSON<{ items: DiscoveryJob[] }>("/api/discovery", {
            signal: controller.signal,
          }),
          requestJSON<DiscoveryConfiguration>("/api/discovery/configuration", {
            signal: controller.signal,
          }),
          requestJSON<{schedule: Schedule | null; min_interval_hours: number; max_runs: number}>("/api/discovery/schedule", {signal:controller.signal}),
        ]);
        if (!stopped) {
          jobs = result.items;
          configuration = config;
          schedule = campaign.schedule;
          minHours = campaign.min_interval_hours; maxRuns = campaign.max_runs;
          if (!scheduleInitialized) {
            scheduleInitialized = true;
            if (schedule) {
              scheduleQuery=schedule.query; scheduleCount=schedule.count; scheduleHours=schedule.interval_hours;
              scheduleRuns=schedule.max_runs; scheduleEnabled=schedule.enabled;
            }
          }
          selectedId ??= jobs[0]?.id ?? null;
          pollError = null;
        }
      } catch (e) {
        if (!stopped)
          pollError = `Progress refresh failed: ${(e as Error).message}. Retrying…`;
      }
      if (!stopped) timer = setTimeout(poll, 4000);
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  });

  async function discoverSongs(event: SubmitEvent) {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    error = null;
    try {
      const job = await requestJSON<DiscoveryJob>("/api/discovery", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt, count }),
      });
      jobs = [job, ...jobs.filter((j) => j.id !== job.id)];
      selectedId = job.id;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      submitting = false;
    }
  }

  async function retryDiscovery(id: string) {
    retrying = true;
    error = null;
    try {
      const job = await requestJSON<DiscoveryJob>(`/api/discovery/${id}/retry`, {
        method: "POST",
      });
      jobs = jobs.map((j) => (j.id === job.id ? job : j));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      retrying = false;
    }
  }

  function trackLabel(track: DiscoveryTrack): string {
    if (track.status === "failed" || track.queue_status === "failed")
      return "Failed";
    if (track.status === "existing") return "Already in your library";
    if (track.status === "imported") return "Imported and indexed";
    if (track.status === "importing" || track.queue_status === "complete")
      return "Audio present · waiting for Jellyfin";
    if (track.queue_status === "running")
      return `Acquiring · ${track.progress}%`;
    if (track.queue_status === "queued")
      return track.next_attempt_at
        ? "Waiting to retry"
        : "Queued for acquisition";
    return "Checking your library";
  }
</script>

<svelte:head><title>Music discovery · Apricott Library</title></svelte:head>

<main class="min-h-screen max-w-screen-xl mx-auto px-6 py-8">
  <nav
    class="flex gap-5 text-sm text-zinc-400 mb-8"
    aria-label="Library navigation"
  >
    <a href="/" class="hover:text-zinc-100">← Library</a>
    <a href="/playlists" class="hover:text-zinc-100">Playlists</a>
    <a href="/import" class="hover:text-zinc-100">Import</a>
  </nav>
  <h1 class="text-3xl text-apricot-400 font-wordmark">Music discovery</h1>
  <p class="text-zinc-400 mt-2 max-w-2xl">
    Describe a vibe. Apricott finds fitting songs, checks your library, and
    automatically acquires missing recordings. You can leave this page while it
    works.
  </p>

  <form
    onsubmit={discoverSongs}
    class="mt-7 rounded-xl border border-zinc-800 bg-zinc-900 p-5 space-y-4"
  >
    <label for="discovery-vibe" class="block text-sm font-medium"
      >What music would you like to add?</label
    >
    <textarea
      id="discovery-vibe"
      bind:value={prompt}
      required
      minlength="3"
      maxlength="4000"
      rows="3"
      placeholder="Rainy-night driving: warm synths, mellow indie, a little nostalgia. Mostly 80s and 90s, no live recordings."
      class="w-full rounded-lg border border-zinc-700 bg-zinc-950 p-3 focus:outline-none focus:border-apricot-400"
    ></textarea>
    <div class="flex flex-wrap gap-5 items-center">
      <label class="flex items-center gap-2 text-sm"
        >Songs
        <input
          type="number"
          bind:value={count}
          min="5"
          max="50"
          required
          class="w-20 rounded-lg border border-zinc-700 bg-zinc-950 p-2"
        />
      </label>
      <button
        type="submit"
        disabled={submitting ||
          !configuration?.ai_configured ||
          !configuration?.can_fetch}
        class="rounded-lg bg-apricot-500 text-zinc-950 px-5 py-2 font-medium disabled:opacity-40"
      >
        {submitting ? "Starting…" : "Discover songs"}
      </button>
    </div>
    {#if configuration && !configuration.ai_configured}
      <p class="text-amber-300 text-sm">
        AI provider setup is needed: configure AI_BASE_URL, AI_MODEL and
        AI_API_KEY on Library's sidecar.
      </p>
    {/if}
    {#if configuration && !configuration.can_fetch}
      <p class="text-amber-300 text-sm">
        Your account needs fetch permission to acquire songs.
      </p>
    {/if}
    <p class="text-xs text-zinc-500">
      Unavailable or uncertain recordings are reported as failures. Only
      verified tracks enter the playlist.
    </p>
  </form>
  {#if error}<p role="alert" class="mt-4 text-red-300">{error}</p>{/if}
  {#if pollError}<p role="status" class="mt-4 text-amber-300">
      {pollError}
    </p>{/if}

  <section class="mt-6 rounded-xl border border-zinc-800 p-5">
    <h2 class="text-lg">Acquisition providers</h2>
    <button type="button" class="text-sm underline text-apricot-300" onclick={loadProviders}>Refresh readiness</button>
    {#each providers as provider}<p class="mt-2 text-sm">{provider.provider}: {provider.ready ? "Configured" : "Unavailable"} · {provider.capability ?? provider.message}</p>{#if provider.capability && provider.message}<p class="text-xs text-zinc-400">{provider.message}</p>{/if}{/each}
  </section>
  <form onsubmit={saveSchedule} class="mt-6 rounded-xl border border-zinc-800 p-5 space-y-3">
    <h2 class="text-lg">Recurring Spotify discovery</h2>
    <p class="text-sm text-zinc-400">A finite campaign finds songs new to Library. Spotify provides metadata; configured audio providers acquire the recordings. No Radio station is created.</p>
    <label class="block text-sm">Spotify search (e.g. genre:country year:2026)<input type="text" required minlength="3" maxlength="500" bind:value={scheduleQuery} class="block w-full bg-zinc-950 border border-zinc-700 rounded p-2" /></label>
    <div class="flex flex-wrap gap-4 text-sm">
      <label>Songs per run <input type="number" min="5" max="50" bind:value={scheduleCount} class="w-20 bg-zinc-950 p-2" /></label>
      <label>Hours between runs <input type="number" min={minHours} max="168" bind:value={scheduleHours} class="w-20 bg-zinc-950 p-2" /></label>
      <label>Maximum runs <input type="number" min="1" max={maxRuns} bind:value={scheduleRuns} class="w-20 bg-zinc-950 p-2" /></label>
      <label><input type="checkbox" bind:checked={scheduleEnabled} />Enable campaign</label>
    </div>
    <button type="submit" disabled={scheduleSaving || !configuration?.can_fetch} class="text-apricot-300 underline">Save campaign (resets run budget)</button>
    {#if schedule}<p class="text-xs text-zinc-400">{schedule.runs}/{schedule.max_runs} runs used · {schedule.enabled ? `Next: ${new Date(schedule.next_run_at).toLocaleString()}` : "Stopped"}</p>{#if schedule.last_error}<p class="text-sm text-amber-300">{schedule.last_error}</p>{/if}{/if}
  </form>
  <div class="mt-8 grid gap-6 md:grid-cols-[260px_1fr]">
    <aside aria-label="Discovery history">
      <h2 class="text-lg mb-3">Discovery history</h2>
      {#if !jobs.length}<p class="text-zinc-500 text-sm">
          Your first discovery will appear here.
        </p>{/if}
      <div class="space-y-2">
        {#each jobs as job (job.id)}
          <button
            type="button"
            onclick={() => (selectedId = job.id)}
            aria-pressed={selectedId === job.id}
            class="w-full text-left rounded-lg p-3 border {selectedId === job.id
              ? 'border-apricot-500 bg-zinc-900'
              : 'border-zinc-800'}"
          >
            <span class="block font-medium">{job.name}</span>
            <span class="block text-xs text-zinc-400 mt-1"
              >{labels[job.status] ?? job.status}</span
            >
            <span class="block text-xs text-zinc-500 mt-1"
              >{job.counts.existing + job.counts.imported}/{job.requested_count} playable</span
            >
          </button>
        {/each}
      </div>
    </aside>
    {#if selected}
      <section
        class="rounded-xl border border-zinc-800 p-5 min-w-0"
        aria-label="Acquisition progress"
      >
        <h2 class="text-xl">{selected.name}</h2>
        <p class="text-zinc-400 text-sm mt-2 whitespace-pre-wrap">
          {selected.prompt}
        </p>
        <p class="mt-4 text-apricot-300" role="status">
          {labels[selected.status] ?? selected.status}
        </p>
        <progress
          max={selected.requested_count}
          value={selected.counts.existing + selected.counts.imported}
          aria-label="Verified playable songs"
          class="w-full mt-3 accent-apricot-500"
        ></progress>
        <div class="flex flex-wrap gap-4 text-sm text-zinc-400 mt-2">
          <span>{selected.counts.existing} already present</span>
          <span>{selected.counts.imported} imported</span>
          <span>{selected.counts.pending} pending</span>
          <span class={selected.counts.failed ? "text-red-300" : ""}
            >{selected.counts.failed} failed</span
          >
        </div>
        {#if selected.suggested_count && selected.suggested_count < selected.requested_count}
          <p class="text-amber-300 text-sm mt-2">
            AI returned {selected.suggested_count} unique suggestions of {selected.requested_count}
            requested.
          </p>
        {/if}
        {#if selected.generation_message}<p class="text-amber-300 text-sm mt-2">{selected.generation_message}</p>{/if}
        {#if selected.error_message}<p
            class="text-red-300 text-sm mt-3"
            role="alert"
          >
            {selected.error_message}
          </p>{/if}
        {#if selected.next_attempt_at && !terminal.has(selected.status) && selected.error_message}
          <p class="text-zinc-400 text-xs mt-2">
            Retry scheduled for {new Date(
              selected.next_attempt_at,
            ).toLocaleTimeString()}.
          </p>
        {/if}
        <div class="flex flex-wrap gap-4 mt-4 text-sm">
          {#if selected.playlist_id}<a
              class="text-apricot-300 underline"
              href={`/playlists/${selected.playlist_id}`}>Open playlist</a
            >{/if}
          {#if ["failed", "partial", "sync_failed"].includes(selected.status) && configuration?.can_fetch}
            <button
              type="button"
              onclick={() => retryDiscovery(selected!.id)}
              disabled={retrying}
              class="underline text-apricot-300 disabled:opacity-40"
            >
              {retrying
                ? "Retrying…"
                : selected.status === "sync_failed"
                  ? "Retry imports"
                  : "Retry failed work"}
            </button>
          {/if}
        </div>
        <ol class="mt-5 divide-y divide-zinc-800">
          {#each selected.tracks as track (track.id)}
            <li class="py-4">
              <div class="flex flex-wrap justify-between gap-2">
                <div>
                  {#if track.jellyfin_item_id}<a
                      class="hover:text-apricot-300"
                      href={`/song/${track.jellyfin_item_id}`}>{track.title}</a
                    >
                  {:else}<span>{track.title}</span>{/if}
                  <p class="text-sm text-zinc-400">{track.artist}</p>
                </div>
                <span
                  class="text-xs {track.status === 'failed' ||
                  track.queue_status === 'failed'
                    ? 'text-red-300'
                    : 'text-zinc-400'}">{trackLabel(track)}</span
                >
              </div>
              {#if track.reason}<p class="text-xs text-zinc-500 mt-1">
                  {track.reason}
                </p>{/if}
              {#if track.attempts}<p class="text-xs text-zinc-500 mt-1">
                  Acquisition attempts: {track.attempts}
                </p>{/if}
              {#if track.error_message}<p class="text-xs text-red-300 mt-2">
                  {track.error_message}
                </p>{/if}
              {#each track.provider_errors ?? [] as provider}<p class="text-xs text-zinc-400 mt-1">{provider.provider} · {provider.code}: {provider.message}</p>{/each}
              {#if track.warning_message}<p class="text-xs text-amber-300 mt-2">
                  {track.warning_message}
                </p>{/if}
            </li>
          {/each}
        </ol>
      </section>
    {/if}
  </div>
</main>
