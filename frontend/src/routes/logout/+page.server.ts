import { redirect } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';
import type { Actions } from './$types';

export const actions: Actions = {
  default: async ({ request, cookies }) => {
    const cookie = request.headers.get('cookie') ?? '';
    await sidecarJSON('/api/auth/logout', { method: 'POST', cookie });
    cookies.delete('apricot_session', { path: '/' });
    throw redirect(303, '/login');
  }
};
