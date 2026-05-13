// Thin fetch wrapper used by SWR.  In dev, the Vite proxy forwards /api/*
// to the FastAPI backend so no BASE_URL is needed.  In prod, set
// VITE_API_BASE_URL="http://<host>:8000" at build time.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  url: string;
  body: string;

  constructor(status: number, url: string, body: string) {
    super(`API ${status} ${url}: ${body.slice(0, 200)}`);
    this.status = status;
    this.url = url;
    this.body = body;
  }
}

export function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const rel = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_URL}${rel}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = apiUrl(path);
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, url, text);
  }
  // Empty body → undefined (keeps TypeScript happy for void-ish endpoints).
  const text = await res.text();
  return (text ? (JSON.parse(text) as T) : (undefined as unknown as T));
}

export async function apiPostJson<TRes, TBody = unknown>(
  path: string,
  body: TBody,
): Promise<TRes> {
  return apiFetch<TRes>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
