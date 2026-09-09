import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

type Workspace = { id: string; name: string };
export function AccountPanel({ workspaceId, onChange }: { workspaceId: string; onChange: (id: string) => void }) {
  const [loggedIn, setLoggedIn] = useState(!!localStorage.getItem("access_token"));
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  useEffect(() => {
    if (!loggedIn) return;
    let active = true;
    api<Workspace[]>("/workspaces").then(items => { if (active) setWorkspaces(items); }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [loggedIn]);
  function selectWorkspace(id: string) {
    client.clear();
    if (id) localStorage.setItem("workspace_id", id); else localStorage.removeItem("workspace_id");
    onChange(id);
  }
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    const credentials = { email: data.get("email"), password: data.get("password") };
    try {
      if (register) {
        await api("/auth/register", { method: "POST", body: JSON.stringify({ ...credentials, full_name: data.get("name") }) });
        setRegister(false);
      }
      const tokens = await api<{ access_token: string; refresh_token: string; mfa_required: boolean }>(data.get("code") ? "/auth/login/mfa" : "/auth/login", { method: "POST", body: JSON.stringify({ ...credentials, code: data.get("code") }) });
      if (tokens.mfa_required) throw new Error("Введите шестизначный код 2FA и нажмите «Войти» ещё раз.");
      localStorage.setItem("access_token", tokens.access_token);
      localStorage.setItem("refresh_token", tokens.refresh_token);
      selectWorkspace(""); setLoggedIn(true);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось войти"); }
    finally { setBusy(false); }
  }
  async function createWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    try {
      const item = await api<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name: new FormData(form).get("workspaceName"), slug: `studio-${crypto.randomUUID()}` }) });
      setWorkspaces(current => [...current, item]); selectWorkspace(item.id); form.reset();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка создания"); }
    finally { setBusy(false); }
  }
  async function logout() {
    setBusy(true); setError("");
    try {
      const refresh = localStorage.getItem("refresh_token");
      if (refresh) await api("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: refresh }) });
    } catch { /* Always clear this browser session even if the server is unavailable. */ }
    localStorage.removeItem("access_token"); localStorage.removeItem("refresh_token");
    selectWorkspace(""); setWorkspaces([]); setLoggedIn(false); setBusy(false);
  }
  return <details className="panel mb-5" open={!workspaceId}>
    <summary className="cursor-pointer font-semibold">{workspaceId ? `Рабочее пространство: ${workspaces.find(w => w.id === workspaceId)?.name ?? "выбрано"}` : "Подключить рабочее пространство"}</summary>
    <p className="hint my-3">Войдите для сохранения контактов и шаблонов на сервере. Редактор и проверка письма доступны без входа.</p>
    {error && <p role="alert" className="error-box">{error}</p>}
    {!loggedIn ? <form onSubmit={login} className="mt-3 flex flex-wrap items-end gap-3">
      {register && <label className="field">Ваше имя<input name="name" required autoComplete="name" /></label>}
      <label className="field">Email<input name="email" type="email" required autoComplete="username" /></label>
      <label className="field">Пароль<input name="password" type="password" required autoComplete={register ? "new-password" : "current-password"} minLength={register ? 10 : 1} /></label>
      {!register && <label className="field">Код 2FA (если включён)<input name="code" inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" /></label>}
      <button className="button primary" disabled={busy}>{busy ? "Подключаем…" : register ? "Создать аккаунт" : "Войти"}</button>
      <button type="button" className="button" onClick={() => { setRegister(!register); setError(""); }}>{register ? "Уже есть аккаунт" : "Регистрация"}</button>
      {register && <p className="hint w-full">Пароль: минимум 10 символов, латинские буквы в верхнем и нижнем регистре, цифра.</p>}
    </form> : <div className="mt-3 flex flex-wrap items-end gap-3">
      <label className="field">Рабочее пространство<select value={workspaceId} onChange={event => selectWorkspace(event.target.value)}><option value="">Выберите пространство</option>{workspaces.map(w => <option value={w.id} key={w.id}>{w.name}</option>)}</select></label>
      <form onSubmit={createWorkspace} className="flex flex-wrap items-end gap-3"><label className="field">Новое пространство<input name="workspaceName" required minLength={2} maxLength={200} placeholder="Моя компания" /></label><button className="button" disabled={busy}>Создать пространство</button></form>
      <button className="button" disabled={busy} onClick={logout}>Выйти</button>
    </div>}
  </details>;
}
