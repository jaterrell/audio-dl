import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("/api/version", () => HttpResponse.json({ version: "2.0.0-test", build: "test" })),
  http.get("/api/settings/defaults", () =>
    HttpResponse.json({
      output_dir: "/tmp/audio-dl-test",
      max_parallel: 4,
      available_formats: ["mp3", "m4a", "flac", "alac", "opus", "wav", "mp4"],
    })
  ),
];

export const server = setupServer(...handlers);
