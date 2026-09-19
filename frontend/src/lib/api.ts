const API_URL = import.meta.env.VITE_API_URL ?? "/api/v1";
export const SESSION_EXPIRED_EVENT = "mailer:session-expired";
export type ApiOptions = RequestInit & { workspaceId?: string };
let refreshing: Promise<void> | null = null;

function expireSession() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("workspace_id");
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  return new Error("Сессия завершена. Войдите снова, чтобы продолжить.");
}

async function refreshSession() {
  if (!refreshing) refreshing = (async () => {
    const refreshToken = localStorage.getItem("refresh_token");
    if (!refreshToken) throw expireSession();
    const response = await fetch(`${API_URL}/auth/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refreshToken }) });
    // A temporary outage must not erase a valid session.
    if (response.status === 401 || response.status === 403) {
      if (refreshToken === localStorage.getItem("refresh_token")) throw expireSession();
      return;
    }
    if (!response.ok) throw new Error("Не удалось восстановить соединение. Попробуйте ещё раз.");
    const tokens = await response.json();
    if (refreshToken !== localStorage.getItem("refresh_token")) return;
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
  })().finally(() => { refreshing = null; });
  return refreshing;
}

export async function api<T>(path: string, options: ApiOptions = {}, retry = true): Promise<T> {
  const authRequest = ["/auth/login", "/auth/login/mfa", "/auth/register", "/auth/refresh", "/auth/logout", "/auth/password/reset-request"].includes(path);
  const token = localStorage.getItem("access_token");
  const workspaceId = options.workspaceId ?? localStorage.getItem("workspace_id");
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token && !authRequest ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId && !authRequest ? { "X-Workspace-ID": workspaceId } : {}),
      ...options.headers,
    },
  });
  if (response.status === 401 && !authRequest) {
    if (!retry) throw expireSession();
    if (token === localStorage.getItem("access_token")) await refreshSession();
    return api<T>(path, options, false);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = Array.isArray(payload.detail) ? payload.detail.map((item: { msg: string }) => item.msg).join("; ") : payload.detail;
    throw new Error(payload?.error?.message ?? detail ?? (response.status === 401 ? "Неверный email или пароль." : `Ошибка сервера ${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
