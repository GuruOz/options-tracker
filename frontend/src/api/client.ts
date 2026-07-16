/** Scope a request to an account: `withAccount("/api/positions", selected)`.
 *
 * Pass "all" for the combined view. Every account-scoped endpoint reads this
 * param, so a panel that forgets it silently falls back to server defaults. */
export function withAccount(path: string, account: string): string {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}account_id=${encodeURIComponent(account)}`;
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export async function deleteJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}
