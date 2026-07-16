/** Scope a request to an account: `withAccount("/api/positions", selected)`.
 *
 * Pass "all" for the combined view. Every account-scoped endpoint reads this
 * param, so a panel that forgets it silently falls back to server defaults. */
export function withAccount(path: string, account: string): string {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}account_id=${encodeURIComponent(account)}`;
}

/** Thrown for a 401 response — the session is gone or was never established.
 * `useAuth` listens for the `auth:unauthorized` event this dispatches and
 * flips the app back to the login screen. */
export class AuthError extends Error {}

function readCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/([.$?*|{}()[\]\\/+^])/g, "\\$1")}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Every request that talks to the backend goes through here so the CSRF
 * header rides along on mutations and a 401 uniformly signals "logged out". */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (MUTATING.has(method)) {
    headers.set("X-CSRF-Token", readCookie("csrf_token") ?? "");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    window.dispatchEvent(new Event("auth:unauthorized"));
    throw new AuthError(`401 for ${path}`);
  }
  return res;
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await apiFetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export async function deleteJSON<T>(path: string): Promise<T> {
  const res = await apiFetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

/** Multipart upload (CSV import). No Content-Type — the browser sets the
 * multipart boundary — but the CSRF header still rides along via apiFetch. */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await apiFetch(path, { method: "POST", body: form });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}
