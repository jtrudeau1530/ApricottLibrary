import { error } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, request }) => {
  const cookie = request.headers.get('cookie') ?? '';
  const { ok, status, data } = await sidecarJSON<{
    id: string;
    title: string;
    artist: string;
    album: string;
    duration_seconds: number | null;
    album_art_url: string | null;
    added_at: string | null;
    description: string;
  }>(`/api/catalog/tracks/${encodeURIComponent(params.id)}`, { cookie });
  if (!ok || !data) throw error(status === 404 ? 404 : 502, 'Track not found');
  return { track: data };
};
