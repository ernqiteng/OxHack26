// The Tempo API (tempo/api/server.py, `make api`). The site is static, so the browser calls it directly.
// On the Vultr box nginx serves the API at /api on the same origin, so the deploy builds with this set to "".
export const API = process.env.NEXT_PUBLIC_TEMPO_API ?? "http://127.0.0.1:8000";

export async function getJSON<T>(path: string, timeoutMs = 4000): Promise<T> {
  const res = await fetch(`${API}${path}`, { signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}
