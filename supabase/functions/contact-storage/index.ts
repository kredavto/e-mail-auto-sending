import postgres from "npm:postgres@3.4.7";
import { tokenHash } from "./deployment-config.ts";

const sql = postgres(Deno.env.get("SUPABASE_DB_URL")!, { prepare: false, max: 1 });
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const respond = (value: unknown, status = 200) => Response.json(value, { status });
Deno.serve(async (req) => {
  const token = req.headers.get("authorization")?.replace(/^Bearer /, "") ?? "";
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)))].map(b => b.toString(16).padStart(2, "0")).join("");
  if (!token || hash !== tokenHash) return respond({ error: "Unauthorized" }, 401);
  if (req.method !== "POST") return respond({ error: "POST required" }, 405);
  try {
    const body = await req.json();
    const { workspace_id: workspace, base_id: base, run_id: run, table_name: table, name, action } = body;
    if (![workspace, base, run].every(x => typeof x === "string" && uuid.test(x))) return respond({ error: "Invalid scope" }, 400);
    if (typeof table !== "string" || !/^[\p{L}\p{N}_]+$/u.test(table) || new TextEncoder().encode(table).length > 63) return respond({ error: "Invalid table name" }, 400);
    if (typeof name !== "string" || name.length > 200) return respond({ error: "Invalid base name" }, 400);
    if (!["begin", "batch", "finish"].includes(action)) return respond({ error: "Invalid action" }, 400);
    const rows = body.contacts ?? [];
    if (!Array.isArray(rows) || rows.length > 1000 || rows.some(c => !uuid.test(c.id) || c.workspace_id !== workspace || typeof c.email !== "string")) return respond({ error: "Invalid contacts" }, 400);
    const result = await sql.begin(async tx => {
      await tx`set local role mailer_contacts_writer`;
      await tx`select set_config('app.workspace_id', ${workspace}, true)`;
      await tx`select pg_advisory_xact_lock(hashtextextended(${workspace + base}, 0))`;
      const records = await tx`select * from mailer_contacts.bases where workspace_id=${workspace} and base_id=${base} for update`;
      const current = records[0];
      if (action === "begin") {
        if (current && current.table_name !== table) {
          await tx`alter table ${tx("mailer_contacts")}.${tx(current.table_name)} rename to ${tx(table)}`;
        }
        await tx`create table if not exists ${tx("mailer_contacts")}.${tx(table)} (
          id uuid primary key, workspace_id uuid not null, email text not null,
          full_name text, company text, position text, phone text,
          status text, is_unsubscribed boolean not null default false,
          data jsonb not null, sync_run uuid not null, synced_at timestamptz not null default now()
        )`;
        await tx`alter table ${tx("mailer_contacts")}.${tx(table)} enable row level security`;
        await tx`alter table ${tx("mailer_contacts")}.${tx(table)} force row level security`;
        await tx`revoke all on ${tx("mailer_contacts")}.${tx(table)} from public, anon, authenticated`;
        if (!current) {
          await tx`create policy workspace_scope on ${tx("mailer_contacts")}.${tx(table)} to mailer_contacts_writer
            using (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
            with check (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)`;
        }
        await tx`insert into mailer_contacts.bases (workspace_id, base_id, name, table_name, sync_run)
          values (${workspace}, ${base}, ${name}, ${table}, ${run})
          on conflict (workspace_id, base_id) do update set name=excluded.name, table_name=excluded.table_name, sync_run=excluded.sync_run`;
        return { table_name: table };
      }
      if (!current || current.sync_run !== run || current.table_name !== table) throw new Error("Stale sync run");
      if (action === "batch" && rows.length) {
        const values = rows.map(c => ({
          id: c.id, workspace_id: workspace, email: c.email, full_name: c.full_name ?? "",
          company: c.company ?? "", position: c.position ?? "", phone: c.phone ?? null,
          status: c.status ?? "new", is_unsubscribed: Boolean(c.is_unsubscribed),
          data: tx.json(c), sync_run: run,
        }));
        await tx`insert into ${tx("mailer_contacts")}.${tx(table)} ${tx(values)}
          on conflict (id) do update set email=excluded.email, full_name=excluded.full_name,
          company=excluded.company, position=excluded.position, phone=excluded.phone,
          status=excluded.status, is_unsubscribed=excluded.is_unsubscribed,
          data=excluded.data, sync_run=excluded.sync_run, synced_at=now()`;
      }
      if (action === "finish") {
        const [{ count }] = await tx`select count(*)::int as count from ${tx("mailer_contacts")}.${tx(table)} where sync_run=${run}`;
        if (count !== body.expected_count) throw new Error("Incomplete snapshot");
        await tx`delete from ${tx("mailer_contacts")}.${tx(table)} where sync_run<>${run}`;
        await tx`update mailer_contacts.bases set contact_count=${count}, synced_at=now()
          where workspace_id=${workspace} and base_id=${base}`;
        return { table_name: table, contact_count: count };
      }
      return { accepted: rows.length };
    });
    return respond(result);
  } catch (error) {
    console.error("Contact storage sync failed", error instanceof Error ? error.message : "unknown");
    return respond({ error: "Contact storage sync failed", detail: error instanceof Error ? error.message : "unknown" }, 500);
  }
});
