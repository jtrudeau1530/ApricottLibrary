import { error } from '@sveltejs/kit';
import { sidecarJSON } from '$lib/server/sidecar';
import type { PageServerLoad } from './$types';

type SongView = {
  track: {
    id: string;
    title: string;
    artist: string;
    album: string;
    duration_seconds: number | null;
    index: number | null;
    disc: number | null;
    description: string;
  };
  album: {
    id: string | null;
    name: string;
    track_count: number;
    duration_seconds: number | null;
    year: number | null;
    cover_url: string | null;
    description: string;
  };
  artist: {
    id: string | null;
    name: string;
    backdrop_url: string | null;
    logo_url: string | null;
  };
  genres: string[];
  tags: string[];
  siblings: Array<{
    id: string;
    title: string;
    index: number | null;
    disc: number | null;
    duration_seconds: number | null;
    is_current: boolean;
  }>;
};

export const load: PageServerLoad = async ({ params, request }) => {
  const cookie = request.headers.get('cookie') ?? '';
  const { ok, status, data } = await sidecarJSON<SongView>(
    `/api/catalog/song/${encodeURIComponent(params.id)}`,
    { cookie }
  );
  if (!ok || !data) throw error(status === 404 ? 404 : 502, 'Track not found');
  return { view: data };
};
