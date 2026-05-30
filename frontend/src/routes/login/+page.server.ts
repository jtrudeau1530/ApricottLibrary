import { fail, redirect } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';
import type { Actions } from './$types';

export const actions: Actions = {
  default: async ({ request, fetch: _f, cookies, url }) => {
    const form = await request.formData();
    const username = String(form.get('username') ?? '').trim();
    const password = String(form.get('password') ?? '');
    if (!username || !password) {
      return fail(400, { error: 'Username and password are required.' });
    }

    const { ok, status, data, setCookie } = await sidecarJSON<{ user: App.User }>(
      '/api/auth/login',
      {
        method: 'POST',
        body: JSON.stringify({ username, password })
      }
    );

    if (!ok || !data?.user) {
      if (status === 401) return fail(401, { error: 'Invalid credentials.' });
      return fail(500, { error: 'Login failed. Try again.' });
    }

    if (setCookie) {
      // Forward sidecar-issued cookie to the browser via SvelteKit.
      const match = setCookie.match(/apricot_session=([^;]+)/);
      if (match) {
        cookies.set('apricot_session', match[1], {
          httpOnly: true,
          secure: process.env.NODE_ENV === 'production',
          sameSite: 'lax',
          path: '/',
          maxAge: 30 * 24 * 60 * 60
        });
      }
    }

    const to = url.searchParams.get('from') || '/';
    throw redirect(303, to);
  }
};
