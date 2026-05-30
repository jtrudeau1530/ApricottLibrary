import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

type PlaylistList = {
  total: number;
  items: Array<{
    id: string;
    name: string;
    owner: string;
    track_count: number | null;
    cover_url: string | null;
  }>;
};

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get('cookie') ?? '';
  const { ok, data, status } = await sidecarJSON<PlaylistList & { detail?: string }>(
    '/api/spotify/playlists?limit=50&offset=0',
    { cookie }
  );
  if (!ok) {
    return {
      playlists: [],
      total: 0,
      error: (data?.detail as string | undefined) ?? `Failed to load playlists (${status}).`
    };
  }
  return { playlists: data?.items ?? [], total: data?.total ?? 0, error: null };
};
