import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, SESSION_EXPIRED_EVENT } from "../lib/api";

type Workspace = { id: string; name: string };
export function AccountPanel({ workspaceId, onChange, onAuthenticated }: { workspaceId: string; onAuthenticated: (value: boolean) => void; onChange: (id: string, preserveDraft?: boolean) => void }) {
  const [loggedIn, setLoggedIn] = useState(!!localStorage.getItem("access_token"));
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const panel = useRef<HTMLElement>(null);
  const loaded = useRef(false);
  const recovering = useRef(false);
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const expired = () => {
      onAuthenticated(false);
      loaded.current = false; recovering.current = true;
      setLoggedIn(false); setWorkspaces([]); setRegister(false); setError("");
      setNotice("Сессия завершена. Войдите снова, чтобы продолжить. Текст открытого письма сохранён в редакторе.");
      client.clear(); onChange("", true);
      panel.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      panel.current?.querySelector<HTMLInputElement>('input[name="email"]')?.focus();
    };
    const storage = (event: StorageEvent) => { if ((event.key === "access_token" || event.key === null) && !localStorage.getItem("access_token")) expired(); };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    window.addEventListener("storage", storage);
    return () => { window.removeEventListener(SESSION_EXPIRED_EVENT, expired); window.removeEventListener("storage", storage); };
  }, [client, onChange, onAuthenticated]);
  useEffect(() => {
    if (!loggedIn || loaded.current) return;
    let active = true;
    api<Workspace[]>("/workspaces").then(items => { if (active) { setWorkspaces(items); onAuthenticated(true); } }).catch(reason => { if (active && localStorage.getItem("access_token")) setError(reason.message); });
    return () => { active = false; };
  }, [loggedIn, onAuthenticated]);
  function selectWorkspace(id: string, preserveDraft = false) {
    client.clear();
    if (id) localStorage.setItem("workspace_id", id); else localStorage.removeItem("workspace_id");
    onChange(id, preserveDraft);
  }
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    const credentials = { email: String(data.get("email") ?? "").trim(), password };
    if (register && (password !== data.get("confirmPassword") || !/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{10,}$/.test(password))) {
      setError(password !== data.get("confirmPassword") ? "Пароли не совпадают." : "Пароль должен содержать минимум 10 символов, заглавную и строчную латинские буквы и цифру.");
      setBusy(false); return;
    }
    if (register && (!String(data.get("name") ?? "").trim() || String(data.get("company") ?? "").trim().length < 2)) {
      setError("Укажите имя и название компании (не менее 2 символов)."); setBusy(false); return;
    }
    if (new TextEncoder().encode(password).length > 72) {
      setError("Пароль слишком длинный. Используйте не более 72 байт (72 латинских символов)."); setBusy(false); return;
    }
    const creatingAccount = register;
    try {
      if (register) {
        await api("/auth/register", { method: "POST", body: JSON.stringify({ ...credentials, full_name: String(data.get("name") ?? "").trim() }) });
        setRegister(false);
      }
      const tokens = await api<{ access_token: string; refresh_token: string; mfa_required: boolean }>(data.get("code") ? "/auth/login/mfa" : "/auth/login", { method: "POST", body: JSON.stringify({ ...credentials, code: data.get("code") }) });
      if (tokens.mfa_required) throw new Error("Введите шестизначный код 2FA и нажмите «Войти» ещё раз.");
      localStorage.setItem("access_token", tokens.access_token);
      localStorage.setItem("refresh_token", tokens.refresh_token);
      onAuthenticated(true);
      loaded.current = true;
      client.clear(); localStorage.removeItem("workspace_id"); setLoggedIn(true); setNotice("");
      if (creatingAccount) {
        const item = await api<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name: String(data.get("company") ?? "").trim(), slug: `studio-${crypto.randomUUID()}` }) });
        setWorkspaces([item]); selectWorkspace(item.id);
        setNotice("Аккаунт создан. Можно загрузить контакты и подготовить первую рассылку.");
      } else {
        const items = await api<Workspace[]>("/workspaces"); setWorkspaces(items);
        selectWorkspace(items[0]?.id ?? "", recovering.current); recovering.current = false;
      }
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
    onAuthenticated(false);
    setBusy(true); setError("");
    try {
      const refresh = localStorage.getItem("refresh_token");
      if (refresh) await api("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: refresh }) });
    } catch { /* Always clear this browser session even if the server is unavailable. */ }
    localStorage.removeItem("access_token"); localStorage.removeItem("refresh_token");
    loaded.current = false; recovering.current = false;
    selectWorkspace(""); setWorkspaces([]); setLoggedIn(false); setBusy(false);
  }
  return <section ref={panel} id="account" aria-label="Аккаунт" className="panel mb-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div>
      <h2 className="font-display text-2xl font-bold">{loggedIn ? "Ваше рабочее пространство" : register ? "Создать аккаунт" : "Вход в аккаунт"}</h2>
      <p className="hint my-3">{loggedIn ? "Контакты, шаблоны и рассылки вашей команды." : register ? "Зарегистрируйтесь, чтобы сохранять базы контактов, письма и расписание рассылок." : "Войдите для работы с контактами и рассылками. Редактор доступен и без входа."}</p>
    </div></div>
    {notice && <p role="status" className="hint mb-3">{notice}</p>}
    {error && <p role="alert" className="error-box">{error}</p>}
    {!loggedIn ? <form aria-label={register ? "Регистрация" : "Вход"} onSubmit={login} className="mt-4 grid max-w-2xl gap-4 sm:grid-cols-2">
      {register && <><label className="field">Ваше имя<input name="name" required maxLength={255} autoComplete="name" placeholder="Имя и фамилия" /></label>
      <label className="field">Название компании или пространства<input name="company" required minLength={2} maxLength={200} autoComplete="organization" placeholder="Моя компания" /></label></>}
      <label className="field sm:col-span-2">Email<input name="email" type="email" required maxLength={255} autoComplete="username" placeholder="name@company.ru" /></label>
      <label className="field">Пароль<input name="password" type={showPassword ? "text" : "password"} required autoComplete={register ? "new-password" : "current-password"} minLength={register ? 10 : 1} aria-describedby={register ? "password-rules" : undefined} /></label>
      {register ? <label className="field">Повторите пароль<input name="confirmPassword" type={showPassword ? "text" : "password"} required autoComplete="new-password" minLength={10} /></label> : <label className="field">Код 2FA (если включён)<input name="code" inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" /></label>}
      <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={showPassword} onChange={e => setShowPassword(e.target.checked)} />Показать пароль</label>
      {register && <p id="password-rules" className="hint sm:col-span-2">Не менее 10 символов, заглавная и строчная латинские буквы и цифра.</p>}
      <button className="button primary" disabled={busy}>{busy ? "Подождите…" : register ? "Зарегистрироваться" : "Войти"}</button>
      <button type="button" className="button" disabled={busy} onClick={() => { setRegister(!register); setError(""); setNotice(""); }}>{register ? "Уже есть аккаунт — войти" : "Создать аккаунт"}</button>
    </form> : <div className="mt-3 flex flex-wrap items-end gap-3">
      <label className="field">Рабочее пространство<select aria-label="Рабочее пространство" value={workspaceId} onChange={event => selectWorkspace(event.target.value)}><option value="">Выберите пространство</option>{workspaces.map(w => <option value={w.id} key={w.id}>{w.name}</option>)}</select></label>
      <form onSubmit={createWorkspace} className="flex flex-wrap items-end gap-3"><label className="field">Новое пространство<input name="workspaceName" required minLength={2} maxLength={200} placeholder="Моя компания" /></label><button className="button" disabled={busy}>Создать пространство</button></form>
      <button className="button" disabled={busy} onClick={logout}>Выйти</button>
    </div>}
  </section>;
}
