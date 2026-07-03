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

/**
 * Force-refresh the CSRF token from a fresh `GET /`.
 *
 * A tab left open across an app relaunch (no reload) still holds the previous
 * launch's `<meta name="csrf-token">` in its unchanged DOM, so every guarded
 * request 403s against the new server. The injected `<meta>`, `?token=`, and
 * dev-only `/api/csrf` are all stale for an un-reloaded page — the only live
 * source is the loopback server, which injects the *current* token into the
 * HTML it serves for `/`. Re-fetch it, parse the fresh token out, replace the
 * cache, and return it (or `null` if none was found).
 */
export async function refreshCsrfTokenFromRoot(): Promise<string | null> {
  try {
    const r = await fetch("/", { headers: { Accept: "text/html" } });
    if (!r.ok) return null;
    const html = await r.text();
    const token = new DOMParser()
      .parseFromString(html, "text/html")
      .querySelector('meta[name="csrf-token"]')
      ?.getAttribute("content");
    if (token) {
      cached = token;
      return token;
    }
  } catch {
    // network error — nothing fresh to hand back
  }
  return null;
}
