const API_URL = import.meta.env.VITE_API_URL ?? "/api/v1";

export type ApiOptions = RequestInit & { workspaceId?: string };
let refreshing: Promise<void> | null = null;

async function refreshSession() {
  if (!refreshing) refreshing = (async () => {
    const refreshToken = localStorage.getItem("refresh_token");
    if (!refreshToken) throw new Error("Сессия истекла. Войдите заново.");
    const response = await fetch(`${API_URL}/auth/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refreshToken }) });
    if (!response.ok) throw new Error("Сессия истекла. Войдите заново через раздел рабочего пространства.");
    const tokens = await response.json();
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
  })().finally(() => { refreshing = null; });
  return refreshing;
}

export async function api<T>(path: string, options: ApiOptions = {}, retry = true): Promise<T> {
  const token = localStorage.getItem("access_token");
  const workspaceId = options.workspaceId ?? localStorage.getItem("workspace_id");
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { "X-Workspace-ID": workspaceId } : {}),
      ...options.headers,
    },
  });
  if (response.status === 401 && retry && !path.startsWith("/auth/")) {
    if (token === localStorage.getItem("access_token")) await refreshSession();
    return api<T>(path, options, false);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = Array.isArray(payload.detail) ? payload.detail.map((item: { msg: string }) => item.msg).join("; ") : payload.detail;
    throw new Error(payload?.error?.message ?? detail ?? (response.status === 401 ? "Сессия истекла. Войдите в аккаунт заново." : `Ошибка сервера ${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

