import { writable, derived, type Readable } from 'svelte/store';

export type QueueItem = {
  id: string;
  spotify_track_id: string;
  track_name: string;
  artist_name: string;
  album_name: string;
  cover_url: string | null;
  status: 'queued' | 'running' | 'complete' | 'failed';
  progress: number;
  error_message: string | null;
  requester_username: string | null;
  created_at: string;
};

export type StorageSnapshot = {
  total_bytes: number;
  used_bytes: number;
  percent_used: number;
};

type SseEvent =
  | { type: 'queue:added'; data: QueueItem }
  | { type: 'queue:running'; data: { id: string } & Partial<QueueItem> }
  | { type: 'queue:progress'; data: { id: string; percent: number } }
  | { type: 'queue:complete'; data: { id: string; output_path: string } }
  | { type: 'queue:error'; data: { id: string; error_message: string } }
  | { type: 'queue:retry'; data: { id: string } }
  | { type: 'queue:hello'; data: { message: string } }
  | { type: 'storage:update'; data: StorageSnapshot };

const queueMap = writable<Record<string, QueueItem>>({});
export const storage = writable<StorageSnapshot | null>(null);
export const connected = writable(false);

let source: EventSource | null = null;

export function startSse() {
  if (typeof window === 'undefined' || source) return;
  source = new EventSource('/api/events');
  source.onopen = () => connected.set(true);
  source.onerror = () => connected.set(false);
  source.onmessage = (e) => {
    try {
      const payload = JSON.parse(e.data) as SseEvent;
      handle(payload);
    } catch {
      /* ignore */
    }
  };
}

export function stopSse() {
  if (source) {
    source.close();
    source = null;
    connected.set(false);
  }
}

function handle(evt: SseEvent) {
  switch (evt.type) {
    case 'queue:added':
      queueMap.update((m) => ({ ...m, [evt.data.id]: evt.data }));
      break;
    case 'queue:running':
      queueMap.update((m) =>
        m[evt.data.id] ? { ...m, [evt.data.id]: { ...m[evt.data.id], status: 'running' } } : m
      );
      break;
    case 'queue:progress':
      queueMap.update((m) =>
        m[evt.data.id]
          ? { ...m, [evt.data.id]: { ...m[evt.data.id], progress: evt.data.percent } }
          : m
      );
      break;
    case 'queue:complete':
      queueMap.update((m) => {
        const next = { ...m };
        delete next[evt.data.id];
        return next;
      });
      break;
    case 'queue:error':
      queueMap.update((m) =>
        m[evt.data.id]
          ? {
              ...m,
              [evt.data.id]: { ...m[evt.data.id], status: 'failed', error_message: evt.data.error_message }
            }
          : m
      );
      break;
    case 'queue:retry':
      queueMap.update((m) =>
        m[evt.data.id]
          ? { ...m, [evt.data.id]: { ...m[evt.data.id], status: 'queued', progress: 0, error_message: null } }
          : m
      );
      break;
    case 'storage:update':
      storage.set(evt.data);
      break;
    case 'queue:hello':
    default:
      break;
  }
}

export function seedQueue(items: QueueItem[]) {
  queueMap.set(Object.fromEntries(items.map((i) => [i.id, i])));
}

export const queueItems: Readable<QueueItem[]> = derived(queueMap, ($m) =>
  Object.values($m).sort((a, b) => (a.created_at < b.created_at ? -1 : 1))
);

export const queueCount: Readable<number> = derived(queueItems, ($q) => $q.length);

export const queuedTrackIds: Readable<Set<string>> = derived(queueItems, ($q) => {
  return new Set($q.map((i) => i.spotify_track_id));
});
