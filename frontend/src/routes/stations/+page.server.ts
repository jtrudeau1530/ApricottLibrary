import { sidecarJSON } from "$lib/server/sidecar";
import type { StationJob, StationConfiguration } from "$lib/station-types";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const [jobs, configuration] = await Promise.all([
    sidecarJSON<{ items: StationJob[] }>("/api/stations", { cookie }),
    sidecarJSON<StationConfiguration>("/api/stations/configuration", {
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
