<script lang="ts">
  let { data } = $props();
</script>

<svelte:head>
  <title>Home · Apricot Library</title>
</svelte:head>

<main class="min-h-screen p-8">
  <header class="flex items-center justify-between mb-8">
    <h1 class="text-3xl font-bold text-apricot-400">Apricot Library</h1>
    <div class="flex items-center gap-3 text-sm">
      <span class="text-zinc-400">Signed in as <strong class="text-zinc-100">{data.user?.username}</strong></span>
      <form method="post" action="/logout">
        <button type="submit" class="rounded-lg bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5">Sign out</button>
      </form>
    </div>
  </header>

  <p class="text-zinc-400">
    Home page placeholder. The full catalog, search, queue, and storage widgets land in Phase 4.
  </p>
</main>
