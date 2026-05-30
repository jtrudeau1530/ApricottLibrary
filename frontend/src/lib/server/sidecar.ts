const SIDECAR_INTERNAL_URL =
  process.env.SIDECAR_INTERNAL_URL || 'http://localhost:8000';

export type SidecarFetchOptions = RequestInit & {
  cookie?: string;
};

export async function sidecarFetch(
  path: string,
  opts: SidecarFetchOptions = {}
): Promise<Response> {
  const { cookie, headers, ...rest } = opts;
  const mergedHeaders = new Headers(headers);
  if (cookie) mergedHeaders.set('cookie', cookie);
  if (!mergedHeaders.has('content-type') && rest.body && typeof rest.body === 'string') {
    mergedHeaders.set('content-type', 'application/json');
  }
  return fetch(`${SIDECAR_INTERNAL_URL}${path}`, { ...rest, headers: mergedHeaders });
}

export async function sidecarJSON<T = unknown>(
  path: string,
  opts: SidecarFetchOptions = {}
): Promise<{ ok: boolean; status: number; data: T | null; setCookie: string | null }> {
  const res = await sidecarFetch(path, opts);
  const setCookie = res.headers.get('set-cookie');
  if (res.status === 204) return { ok: res.ok, status: res.status, data: null, setCookie };
  let data: T | null = null;
  try {
    data = (await res.json()) as T;
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, data, setCookie };
}
