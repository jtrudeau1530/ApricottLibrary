<script lang="ts">
  import { invalidateAll } from '$app/navigation';

  type AdminUser = {
    id: string;
    username: string;
    disabled: boolean;
    is_admin: boolean;
    permissions: Record<string, unknown>;
    created_at: string;
  };

  let { data } = $props();
  let users = $derived(data.users as AdminUser[]);

  let creating = $state(false);
  let form = $state({
    username: '',
    password: '',
    is_admin: false,
    can_fetch: true,
    can_edit_metadata: false
  });
  let createError = $state<string | null>(null);

  async function createUser() {
    creating = true;
    createError = null;
    try {
      const res = await fetch('/api/admin/users', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(form)
      });
      if (!res.ok) {
        if (res.status === 409) throw new Error('Username already taken.');
        throw new Error(`Create failed (${res.status})`);
      }
      form = {
        username: '',
        password: '',
        is_admin: false,
        can_fetch: true,
        can_edit_metadata: false
      };
      await invalidateAll();
    } catch (e) {
      createError = (e as Error).message;
    } finally {
      creating = false;
    }
  }

  async function toggleDisabled(u: AdminUser) {
    await fetch(`/api/admin/users/${u.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ disabled: !u.disabled })
    });
    await invalidateAll();
  }

  async function setPermission(u: AdminUser, key: 'can_fetch' | 'can_edit_metadata', value: boolean) {
    await fetch(`/api/admin/users/${u.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ [key]: value })
    });
    await invalidateAll();
  }

  async function resetPassword(u: AdminUser) {
    const next = prompt(`New password for ${u.username} (min 6 chars):`);
    if (!next || next.length < 6) return;
    await fetch(`/api/admin/users/${u.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: next })
    });
    alert('Password updated; their existing sessions were invalidated.');
  }

  // ---- YouTube cookies ----
  let cookiesPresent = $state<boolean>(Boolean(data.youtube_cookies_present));
  let uploadingCookies = $state(false);
  let cookiesError = $state<string | null>(null);
  let cookiesFile = $state<FileList | null>(null);

  async function uploadCookies() {
    if (!cookiesFile || cookiesFile.length === 0) return;
    uploadingCookies = true;
    cookiesError = null;
    try {
      const fd = new FormData();
      fd.append('file', cookiesFile[0]);
      const res = await fetch('/api/admin/youtube/cookies', { method: 'POST', body: fd });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `Upload failed (${res.status})` }));
        throw new Error(String(body.detail ?? `Upload failed (${res.status})`));
      }
      cookiesPresent = true;
      cookiesFile = null;
    } catch (e) {
      cookiesError = (e as Error).message;
    } finally {
      uploadingCookies = false;
    }
  }

  async function clearCookies() {
    if (!confirm('Remove the YouTube cookies? Downloads will likely fail for any video YouTube flags as bot traffic until you upload a new file.')) return;
    const res = await fetch('/api/admin/youtube/cookies', { method: 'DELETE' });
    if (res.ok) cookiesPresent = false;
  }
</script>

<svelte:head>
  <title>Admin · Apricott Library</title>
</svelte:head>

<main class="min-h-screen p-6 max-w-4xl mx-auto space-y-8">
  <header class="flex items-center justify-between">
    <h1 class="text-2xl font-bold text-apricot-400">Admin</h1>
    <a href="/" class="text-sm text-zinc-400 hover:text-apricot-400">← Home</a>
  </header>

  <section class="rounded-2xl bg-zinc-900 p-5 space-y-4">
    <h2 class="font-semibold">Create user</h2>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        createUser();
      }}
      class="grid sm:grid-cols-2 gap-3"
    >
      <input
        bind:value={form.username}
        placeholder="Username"
        required
        class="rounded-lg bg-zinc-800 px-3 py-2"
      />
      <input
        type="password"
        bind:value={form.password}
        placeholder="Initial password"
        required
        minlength="6"
        class="rounded-lg bg-zinc-800 px-3 py-2"
      />
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={form.can_fetch} /> Can fetch
      </label>
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={form.can_edit_metadata} /> Can edit metadata
      </label>
      <label class="flex items-center gap-2 text-sm sm:col-span-2">
        <input type="checkbox" bind:checked={form.is_admin} /> Make admin
      </label>
      {#if createError}
        <p class="sm:col-span-2 text-sm text-red-400">{createError}</p>
      {/if}
      <button
        type="submit"
        disabled={creating}
        class="sm:col-span-2 rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold py-2 disabled:opacity-50"
      >
        {creating ? 'Creating…' : 'Create user'}
      </button>
    </form>
  </section>

  <section class="rounded-2xl bg-zinc-900 p-5 space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="font-semibold">YouTube cookies</h2>
      <span
        class="text-xs px-2 py-0.5 rounded-full {cookiesPresent ? 'bg-apricot-900 text-apricot-200' : 'bg-zinc-800 text-zinc-400'}"
      >
        {cookiesPresent ? 'Active' : 'Not uploaded'}
      </span>
    </div>
    <p class="text-xs text-zinc-500 leading-relaxed">
      YouTube blocks unauthenticated downloads from headless servers
      (<em>"Sign in to confirm you're not a bot"</em>). Install a browser extension like
      <a class="text-apricot-400 hover:underline" href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank" rel="noopener">Get cookies.txt LOCALLY</a>,
      sign in to YouTube, export <code>cookies.txt</code>, and upload it here. yt-dlp will use it
      for every video download. The file is stored on the sidecar volume at
      <code>/data/youtube_cookies.txt</code>.
    </p>
    <div class="flex flex-wrap items-center gap-3">
      <input
        type="file"
        accept=".txt,text/plain"
        onchange={(e) => (cookiesFile = (e.currentTarget as HTMLInputElement).files)}
        class="text-xs file:rounded file:bg-zinc-800 file:border-0 file:px-3 file:py-1.5 file:text-zinc-100 file:mr-3"
      />
      <button
        type="button"
        onclick={uploadCookies}
        disabled={uploadingCookies || !cookiesFile || cookiesFile.length === 0}
        class="text-sm rounded-lg bg-apricot-500 hover:bg-apricot-600 text-zinc-950 font-semibold px-3 py-1.5 disabled:opacity-50"
      >
        {uploadingCookies ? 'Uploading…' : 'Upload'}
      </button>
      {#if cookiesPresent}
        <button
          type="button"
          onclick={clearCookies}
          class="text-xs rounded bg-zinc-800 hover:bg-zinc-700 px-2 py-1"
        >
          Remove
        </button>
      {/if}
    </div>
    {#if cookiesError}
      <p class="text-sm text-red-400">{cookiesError}</p>
    {/if}
  </section>

  <section class="rounded-2xl bg-zinc-900">
    <h2 class="px-5 py-4 border-b border-zinc-800 font-semibold">Users</h2>
    <ul class="divide-y divide-zinc-800">
      {#each users as u (u.id)}
        <li class="px-5 py-3 flex items-center gap-4 flex-wrap">
          <div class="flex-1 min-w-0">
            <p class="font-medium">
              {u.username}
              {#if u.is_admin}<span class="ml-2 text-xs px-1.5 py-0.5 rounded bg-apricot-900 text-apricot-200">admin</span>{/if}
              {#if u.disabled}<span class="ml-2 text-xs px-1.5 py-0.5 rounded bg-red-900 text-red-200">disabled</span>{/if}
            </p>
          </div>
          <label class="text-xs flex items-center gap-1">
            <input
              type="checkbox"
              checked={Boolean(u.permissions.can_fetch)}
              onchange={(e) => setPermission(u, 'can_fetch', (e.currentTarget as HTMLInputElement).checked)}
            />
            fetch
          </label>
          <label class="text-xs flex items-center gap-1">
            <input
              type="checkbox"
              checked={Boolean(u.permissions.can_edit_metadata)}
              onchange={(e) =>
                setPermission(u, 'can_edit_metadata', (e.currentTarget as HTMLInputElement).checked)}
            />
            edit-metadata
          </label>
          <button
            type="button"
            onclick={() => resetPassword(u)}
            class="text-xs rounded bg-zinc-800 hover:bg-zinc-700 px-2 py-1"
          >
            Reset password
          </button>
          <button
            type="button"
            onclick={() => toggleDisabled(u)}
            class="text-xs rounded bg-zinc-800 hover:bg-zinc-700 px-2 py-1"
          >
            {u.disabled ? 'Enable' : 'Disable'}
          </button>
        </li>
      {/each}
    </ul>
  </section>
</main>
