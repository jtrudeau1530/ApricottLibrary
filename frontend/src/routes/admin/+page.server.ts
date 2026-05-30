import { error } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, request }) => {
  if (!locals.user?.is_admin) throw error(403, 'Admin only');
  const cookie = request.headers.get('cookie') ?? '';
  const { data } = await sidecarJSON<{ items: unknown[] }>('/api/admin/users', { cookie });
  return { users: data?.items ?? [] };
};
