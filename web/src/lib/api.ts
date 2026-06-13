import { discoverCsrfToken } from "./csrf";
import type { Format, VersionInfo } from "./types";

async function csrfHeaders(): Promise<HeadersInit> {
  const token = await discoverCsrfToken();
  return token
    ? { "X-Audio-DL-Token": token, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

export async function getVersion(): Promise<VersionInfo> {
  const r = await fetch("/api/version");
  if (!r.ok) throw new Error(`/api/version ${r.status}`);
  return r.json();
}

export async function getDefaults(): Promise<{
  output_dir: string;
  max_parallel: number;
  available_formats: Format[];
}> {
  const r = await fetch("/api/settings/defaults");
  if (!r.ok) throw new Error(`/api/settings/defaults ${r.status}`);
  return r.json();
}

export interface PostJobsRequest {
  url: string;
  format: Format;
}

export async function postJobs(urls: PostJobsRequest[]): Promise<{ job_id: string }> {
  const r = await fetch("/jobs", {
    method: "POST",
    headers: await csrfHeaders(),
    body: JSON.stringify({ urls }),
  });
  if (!r.ok) throw new Error(`/jobs ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function cancelJob(jobId: string): Promise<{ cancelled: boolean }> {
  const r = await fetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: await csrfHeaders(),
  });
  if (!r.ok) throw new Error(`cancel ${r.status}`);
  return r.json();
}

export async function reveal(path: string): Promise<{ ok: boolean }> {
  const r = await fetch("/reveal", {
    method: "POST",
    headers: await csrfHeaders(),
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`/reveal ${r.status}`);
  return r.json();
}
