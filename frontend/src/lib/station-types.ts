export type StationTrack = {
  id: string;
  title: string;
  artist: string;
  reason: string;
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

export type StationJob = {
  id: string;
  name: string;
  prompt: string;
  requested_count: number;
  suggested_count: number;
  status: string;
  publish_radio: boolean;
  error_message: string | null;
  playlist_id: string | null;
  radio_station_id: string | null;
  radio_url: string | null;
  counts: {
    existing: number;
    imported: number;
    failed: number;
    downloaded: number;
    pending: number;
  };
  tracks: StationTrack[];
  next_attempt_at: string | null;
  created_at: string;
  updated_at: string;
};

export type StationConfiguration = {
  ai_configured: boolean;
  radio_configured: boolean;
  can_fetch: boolean;
  concurrency: number;
  max_attempts: number;
};
