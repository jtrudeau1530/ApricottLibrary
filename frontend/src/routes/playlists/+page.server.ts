import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get('cookie') ?? '';
  const { data } = await sidecarJSON<{ items: unknown[] }>('/api/playlists', { cookie });
  return { playlists: data?.items ?? [] };
};
