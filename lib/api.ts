function normalizeApiBaseUrl(configured?: string | null): string | null {
  const trimmed = configured?.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replace(/\/+$/, "");
  return normalized.endsWith("/api") ? normalized : `${normalized}/api`;
}

const PRODUCTION_API_BASE = "https://antigravity-backend-2oaj.onrender.com/api";

export function getApiBaseUrl(): string {
  const configured = normalizeApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);
  if (configured) return configured;

  if (typeof window !== "undefined") {
    const { hostname } = window.location;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      const host = hostname === "127.0.0.1" ? "127.0.0.1" : "localhost";
      return `http://${host}:8000/api`;
    }
    return PRODUCTION_API_BASE;
  }

  return process.env.NODE_ENV === "development"
    ? "http://localhost:8000/api"
    : PRODUCTION_API_BASE;
}
