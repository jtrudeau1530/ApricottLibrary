<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type {
    StationJob,
    StationConfiguration,
    StationTrack,
  } from "$lib/station-types";

  let { data } = $props();
  let jobs = $state<StationJob[]>(untrack(() => data.jobs));
  let configuration = $state<StationConfiguration | null>(
    untrack(() => data.configuration),
  );
  let selectedId = $state<string | null>(
    untrack(() => data.jobs[0]?.id ?? null),
  );
  let selected = $derived(jobs.find((job) => job.id === selectedId));
  let prompt = $state("");
  let count = $state(20);
  let publishRadio = $state(
    untrack(() => Boolean(data.configuration?.radio_configured)),
  );
  let submitting = $state(false);
  let retrying = $state(false);
  let error = $state<string | null>(untrack(() => data.error));
  let pollError = $state<string | null>(null);
  const terminal = new Set(["ready", "partial", "failed", "sync_failed"]);
  const labels: Record<string, string> = {
    queued: "Waiting to start",
    planning: "Finding songs and checking your library",
    acquiring: "Acquiring and importing music",
    syncing: "Connecting to Radio",
    ready: "Ready",
    partial: "Ready with missing tracks",
    failed: "Needs attention",
    sync_failed: "Playlist ready · Radio sync failed",
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
    async function poll() {
      try {
        const [result, config] = await Promise.all([
          requestJSON<{ items: StationJob[] }>("/api/stations", {
            signal: controller.signal,
          }),
          requestJSON<StationConfiguration>("/api/stations/configuration", {
            signal: controller.signal,
          }),
        ]);
        if (!stopped) {
          jobs = result.items;
          configuration = config;
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

  async function makeStation(event: SubmitEvent) {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    error = null;
    try {
      const job = await requestJSON<StationJob>("/api/stations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt, count, publish_radio: publishRadio }),
      });
      jobs = [job, ...jobs.filter((j) => j.id !== job.id)];
      selectedId = job.id;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      submitting = false;
    }
  }

  async function retryStation(id: string) {
    retrying = true;
    error = null;
    try {
      const job = await requestJSON<StationJob>(`/api/stations/${id}/retry`, {
        method: "POST",
      });
      jobs = jobs.map((j) => (j.id === job.id ? job : j));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      retrying = false;
    }
  }

  function trackLabel(track: StationTrack): string {
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

<svelte:head><title>AI station maker · Apricott Library</title></svelte:head>

<main class="min-h-screen max-w-screen-xl mx-auto px-6 py-8">
  <nav
    class="flex gap-5 text-sm text-zinc-400 mb-8"
    aria-label="Library navigation"
  >
    <a href="/" class="hover:text-zinc-100">← Library</a>
    <a href="/playlists" class="hover:text-zinc-100">Playlists</a>
    <a href="/import" class="hover:text-zinc-100">Import</a>
  </nav>
  <h1 class="text-3xl text-apricot-400 font-wordmark">AI station maker</h1>
  <p class="text-zinc-400 mt-2 max-w-2xl">
    Describe a vibe. Apricott finds fitting songs, checks your library, and
    automatically acquires missing recordings. You can leave this page while it
    works.
  </p>

  <form
    onsubmit={makeStation}
    class="mt-7 rounded-xl border border-zinc-800 bg-zinc-900 p-5 space-y-4"
  >
    <label for="station-vibe" class="block text-sm font-medium"
      >What should this station feel like?</label
    >
    <textarea
      id="station-vibe"
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
      <label class="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          bind:checked={publishRadio}
          disabled={!configuration?.radio_configured}
        />
        Create a Radio station too
      </label>
      <button
        type="submit"
        disabled={submitting ||
          !configuration?.ai_configured ||
          !configuration?.can_fetch}
        class="rounded-lg bg-apricot-500 text-zinc-950 px-5 py-2 font-medium disabled:opacity-40"
      >
        {submitting ? "Starting…" : "Make station"}
      </button>
    </div>
    {#if configuration && !configuration.ai_configured}
      <p class="text-amber-300 text-sm">
        AI provider setup is needed: configure AI_BASE_URL, AI_MODEL and
        AI_API_KEY on Library's sidecar.
      </p>
    {/if}
    {#if configuration && !configuration.radio_configured}
      <p class="text-zinc-400 text-sm">
        Radio is not connected yet. Stations will be saved as Library playlists.
      </p>
    {/if}
    {#if configuration && !configuration.can_fetch}
      <p class="text-amber-300 text-sm">
        Your account needs fetch permission to create stations.
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

  <div class="mt-8 grid gap-6 md:grid-cols-[260px_1fr]">
    <aside aria-label="Station history">
      <h2 class="text-lg mb-3">Your stations</h2>
      {#if !jobs.length}<p class="text-zinc-500 text-sm">
          Your first station will appear here.
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
        aria-label="Station progress"
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
          {#if selected.radio_url}<a
              class="text-apricot-300 underline"
              href={selected.radio_url}>Open Radio station</a
            >
          {:else if selected.radio_station_id}<span class="text-apricot-300"
              >Radio station: {selected.radio_station_id}</span
            >{/if}
          {#if ["failed", "partial", "sync_failed"].includes(selected.status) && configuration?.can_fetch}
            <button
              type="button"
              onclick={() => retryStation(selected!.id)}
              disabled={retrying}
              class="underline text-apricot-300 disabled:opacity-40"
            >
              {retrying
                ? "Retrying…"
                : selected.status === "sync_failed"
                  ? "Retry Radio sync"
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
