/**
 * Backend API origin from Vite env (build-time / .env*).
 * Production builds must set VITE_API_URL to the Railway API host.
 * Empty string → same-origin relative paths (local SPA served by FastAPI).
 */
const raw = (import.meta.env.VITE_API_URL as string | undefined)?.trim() ?? "";

export const API_BASE = raw.replace(/\/$/, "");

export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalized}`;
}
