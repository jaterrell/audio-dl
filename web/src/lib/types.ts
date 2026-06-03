export type Format = "mp3" | "m4a" | "flac" | "alac" | "opus" | "wav" | "mp4";

export const AUDIO_FORMATS: Format[] = ["mp3", "m4a", "flac", "alac", "opus", "wav"];
export const VIDEO_FORMATS: Format[] = ["mp4"];
export const ALL_FORMATS: Format[] = [...AUDIO_FORMATS, ...VIDEO_FORMATS];

export type UrlStateName = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface UrlState {
  url: string;
  media_format: Format;
  state: UrlStateName;
  progress_percent: number;
  speed: string | null;
  eta: string | null;
  paths: string[];
  error: string | null;
  thumb_id: string | null;
  title: string | null;
  uploader: string | null;
}

export interface JobSnapshot {
  job_id: string;
  state: UrlStateName;
  started_at: number;
  urls: UrlState[];
}

export interface HistoryItem {
  url: string;
  title: string | null;
  artist: string | null;
  media_format: Format;
  paths: string[];
  thumb_id: string | null;
  added_at: number;
}

export interface Settings {
  default_format: Format;
  output_dir: string;
  max_parallel: number;
}

export interface VersionInfo {
  version: string;
  build: string;
}
