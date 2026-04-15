function normalizeApiBaseUrl(configured?: string | null): string | null {
  const trimmed = configured?.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replace(/\/+$/, "");
  return normalized.endsWith("/api") ? normalized : `${normalized}/api`;
}

export function getApiBaseUrl(): string {
  const configured = normalizeApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);
  if (configured) return configured;

  if (typeof window !== "undefined") {
    const host = window.location.hostname === "127.0.0.1" ? "127.0.0.1" : "localhost";
    return `http://${host}:8000/api`;
  }

  return "http://localhost:8000/api";
}

