import type { Dashboard, Discrepancy, Explanation, User } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

type ApiError = { error?: string };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: init.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  const payload = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with ${response.status}`);
  return payload;
}

export const api = {
  me: () => request<{ user: User | null }>("/api/me"),
  login: (email: string, password: string) => request<{ user: User }>("/api/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  signup: (email: string, password: string) => request<{ user: User }>("/api/signup", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ ok: boolean }>("/api/logout", { method: "POST", body: JSON.stringify({}) }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  importCsvs: (orders: File, payments: File) => {
    const form = new FormData();
    form.append("orders", orders);
    form.append("payments", payments);
    return request<{ orders: number; payments: number; dashboard: Dashboard }>("/api/import", { method: "POST", body: form });
  },
  explain: (rows: Discrepancy[]) => request<{ cached: boolean; explanation: Explanation }>("/api/explain", { method: "POST", body: JSON.stringify({ rows }) }),
};
