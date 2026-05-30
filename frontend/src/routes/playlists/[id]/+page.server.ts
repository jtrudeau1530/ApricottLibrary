import { error } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, request }) => {
  const cookie = request.headers.get('cookie') ?? '';
  const { ok, status, data } = await sidecarJSON<{
    id: string;
    name: string;
    owner_id: string | null;
    is_global: boolean;
    items: Array<{ id: string; jellyfin_item_id: string; position: number }>;
  }>(`/api/playlists/${encodeURIComponent(params.id)}`, { cookie });
  if (!ok || !data) throw error(status === 404 ? 404 : 502, 'Playlist not found');

  // Resolve track metadata for each item via catalog.
  const tracks = await Promise.all(
    data.items.map(async (it) => {
      const t = await sidecarJSON<{
        id: string;
        title: string;
        artist: string;
        album: string;
        album_art_url: string | null;
      }>(`/api/catalog/tracks/${encodeURIComponent(it.jellyfin_item_id)}`, { cookie });
      return { row_id: it.id, track: t.data };
    })
  );

  return { playlist: data, tracks };
};
