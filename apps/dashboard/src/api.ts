let csrf: string | null = null;

export function setCsrf(value: string | null) {
  csrf = value;
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;
  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET") {
    headers.set("Idempotency-Key", headers.get("Idempotency-Key") ?? crypto.randomUUID());
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    throw new ApiError(
      0,
      "NETWORK_UNAVAILABLE",
      "Cannot reach the local API. Check the native server.",
      null,
    );
  }
  if (!response.ok) {
    const payload: unknown = await response.json();
    const data = typeof payload === "object" && payload !== null ? payload : {};
    const message =
      "message" in data && typeof data.message === "string"
        ? data.message
        : "The request could not be completed";
    const code = "code" in data && typeof data.code === "string" ? data.code : "REQUEST_FAILED";
    throw new ApiError(response.status, code, message, response.headers.get("X-Request-ID"));
  }
  return response.json() as Promise<T>;
}

export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });

export async function download(path: string, filename: string) {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok)
    throw new ApiError(
      response.status,
      "EXPORT_FAILED",
      "Case export could not be retrieved",
      null,
    );
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function queryString(values: Record<string, string | number | null | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  return query.toString();
}
