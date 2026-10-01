export type DiscoveryTrack = {
  id: string;
  title: string;
  artist: string;
  reason: string;
  provider_errors?: { provider: string; code: string; message: string }[];
  status: string;
  match_source: string | null;
  jellyfin_item_id: string | null;
  queue_status: string | null;
  progress: number;
  attempts: number;
  error_message: string | null;
  warning_message: string | null;
  next_attempt_at: string | null;
};

export type DiscoveryJob = {
  id: string;
  name: string;
  generation_message?: string | null;
  prompt: string;
  requested_count: number;
  suggested_count: number;
  status: string;
  error_message: string | null;
  playlist_id: string | null;
  counts: {
    existing: number;
    imported: number;
    failed: number;
    downloaded: number;
    pending: number;
  };
  tracks: DiscoveryTrack[];
  next_attempt_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DiscoveryConfiguration = {
  ai_configured: boolean;
  can_fetch: boolean;
  concurrency: number;
  max_attempts: number;
};
