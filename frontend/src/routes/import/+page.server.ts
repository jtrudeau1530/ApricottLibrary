import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get('cookie') ?? '';
  const { data } = await sidecarJSON<{
    total: number;
    items: Array<{
      id: string;
      name: string;
      owner: string;
      track_count: number | null;
      cover_url: string | null;
    }>;
  }>('/api/spotify/playlists?limit=50&offset=0', { cookie });
  return { playlists: data?.items ?? [], total: data?.total ?? 0 };
};
