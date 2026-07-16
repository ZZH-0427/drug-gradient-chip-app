export interface ApiBaseUrlOptions {
  configuredUrl?: string;
  isDevelopment: boolean;
}

export function resolveApiBaseUrl({ configuredUrl, isDevelopment }: ApiBaseUrlOptions): string {
  const configured = configuredUrl?.trim();
  if (configured) {
    return stripTrailingSlashes(configured);
  }
  return isDevelopment ? "http://127.0.0.1:8000" : "";
}

function stripTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, "");
}
