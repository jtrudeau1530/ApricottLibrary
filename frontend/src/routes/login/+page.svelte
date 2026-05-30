<script lang="ts">
  import { enhance } from '$app/forms';

  let { form } = $props();
  let submitting = $state(false);
</script>

<svelte:head>
  <title>Sign in · Apricot Library</title>
</svelte:head>

<div class="min-h-screen grid place-items-center px-4">
  <div class="w-full max-w-sm rounded-2xl bg-zinc-900 p-8 shadow-xl">
    <h1 class="text-2xl font-semibold mb-1 text-apricot-400">Apricot Library</h1>
    <p class="text-sm text-zinc-400 mb-6">Sign in to continue.</p>

    <form
      method="post"
      use:enhance={() => {
        submitting = true;
        return async ({ update }) => {
          await update();
          submitting = false;
        };
      }}
      class="space-y-4"
    >
      <label class="block">
        <span class="block text-sm text-zinc-300 mb-1">Username</span>
        <input
          name="username"
          type="text"
          autocomplete="username"
          required
          class="w-full rounded-lg bg-zinc-800 px-3 py-2 outline-none focus:ring-2 focus:ring-apricot-500"
        />
      </label>
      <label class="block">
        <span class="block text-sm text-zinc-300 mb-1">Password</span>
        <input
          name="password"
          type="password"
          autocomplete="current-password"
          required
          class="w-full rounded-lg bg-zinc-800 px-3 py-2 outline-none focus:ring-2 focus:ring-apricot-500"
        />
      </label>

      {#if form?.error}
        <p class="text-sm text-red-400">{form.error}</p>
      {/if}

      <button
        type="submit"
        disabled={submitting}
        class="w-full rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold py-2 disabled:opacity-50"
      >
        {submitting ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  </div>
</div>
