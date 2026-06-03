let cached: string | null = null;

export async function discoverCsrfToken(): Promise<string> {
  if (cached !== null) return cached;
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
