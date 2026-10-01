import { sidecarJSON } from "$lib/server/sidecar";
import type { DiscoveryJob, DiscoveryConfiguration } from "$lib/discovery-types";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const [jobs, configuration] = await Promise.all([
    sidecarJSON<{ items: DiscoveryJob[] }>("/api/discovery", { cookie }),
    sidecarJSON<DiscoveryConfiguration>("/api/discovery/configuration", {
      cookie,
    }),
  ]);
  return {
    jobs: jobs.data?.items ?? [],
    configuration: configuration.data,
    error:
      !jobs.ok || !configuration.ok
        ? "Could not load station jobs. Retrying…"
        : null,
  };
};
