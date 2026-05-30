import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get('cookie') ?? '';

  const [tracks, queue, storage, playlists] = await Promise.all([
    sidecarJSON<{ count: number; total: number; items: unknown[] }>(
      '/api/catalog/tracks?sort=added&descending=true&limit=200&offset=0',
      { cookie }
    ),
    sidecarJSON<{ count: number; items: unknown[] }>('/api/queue', { cookie }),
    sidecarJSON<{ total_bytes: number; used_bytes: number; percent_used: number }>(
      '/api/storage',
      { cookie }
    ),
    sidecarJSON<{ items: unknown[] }>('/api/playlists', { cookie })
  ]);

  return {
    tracks: tracks.data ?? { count: 0, total: 0, items: [] },
    queue: queue.data?.items ?? [],
    storage: storage.data ?? null,
    playlists: playlists.data?.items ?? []
  };
};
