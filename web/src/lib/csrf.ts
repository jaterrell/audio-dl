let cached: string | null = null;

export async function discoverCsrfToken(): Promise<string> {
  if (cached !== null) return cached;
  // Prefer the token the loopback server injects into index.html — it survives
  // bare-URL visits (no ?token=) and app relaunches (token rotates per launch).
  const fromMeta = document
    .querySelector('meta[name="csrf-token"]')
    ?.getAttribute("content");
  if (fromMeta) {
    cached = fromMeta;
    return fromMeta;
  }
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    cached = fromUrl;
    return fromUrl;
  }
  try {
    const r = await fetch("/api/csrf");
    if (r.ok) {
      const data = (await r.json()) as { token?: string };
      cached = data.token ?? "";
      return cached;
    }
  } catch {
    // network error in dev — fall through
  }
  cached = "";
  return "";
}

export function resetCsrfCache() {
  cached = null;
}
