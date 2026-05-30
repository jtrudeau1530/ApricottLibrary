import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';

const PUBLIC_ROUTES = new Set(['/login', '/health']);

export const handle: Handle = async ({ event, resolve }) => {
  if (event.url.pathname === '/health') {
    return new Response('ok', { status: 200 });
  }

  const cookie = event.request.headers.get('cookie') ?? '';
  let user: App.User | null = null;
  if (cookie.includes('apricot_session=')) {
    const { ok, data } = await sidecarJSON<{ user: App.User }>('/api/auth/me', { cookie });
    if (ok && data?.user) user = data.user;
  }
  event.locals.user = user;

  const path = event.url.pathname;
  const isPublic = PUBLIC_ROUTES.has(path) || path.startsWith('/api');

  if (!user && !isPublic) {
    throw redirect(303, `/login?from=${encodeURIComponent(path)}`);
  }
  if (user && path === '/login') {
    throw redirect(303, '/');
  }

  return resolve(event);
};
