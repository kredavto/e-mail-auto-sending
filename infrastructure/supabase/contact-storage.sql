-- Dedicated server-only role and private schema. No browser/API access.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mailer_contacts_writer') THEN
    CREATE ROLE mailer_contacts_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
GRANT mailer_contacts_writer TO postgres;
CREATE SCHEMA IF NOT EXISTS mailer_contacts AUTHORIZATION mailer_contacts_writer;
REVOKE ALL ON SCHEMA mailer_contacts FROM PUBLIC, anon, authenticated;
GRANT USAGE, CREATE ON SCHEMA mailer_contacts TO mailer_contacts_writer;
GRANT CONNECT ON DATABASE postgres TO mailer_contacts_writer;
CREATE TABLE IF NOT EXISTS mailer_contacts.bases (
  workspace_id uuid NOT NULL,
  base_id uuid NOT NULL,
  name text NOT NULL,
  table_name text NOT NULL UNIQUE,
  contact_count bigint NOT NULL DEFAULT 0,
  synced_at timestamptz,
  sync_run uuid,
  PRIMARY KEY (workspace_id, base_id)
);
ALTER TABLE mailer_contacts.bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE mailer_contacts.bases FORCE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON mailer_contacts.bases TO mailer_contacts_writer;
CREATE POLICY workspace_scope ON mailer_contacts.bases TO mailer_contacts_writer
  USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
  WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid);
REVOKE ALL ON ALL TABLES IN SCHEMA mailer_contacts FROM PUBLIC, anon, authenticated;
