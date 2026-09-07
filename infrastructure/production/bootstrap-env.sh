#!/bin/sh
set -eu

env_file=${1:-.env}

if [ -e "$env_file" ]; then
  echo "$env_file already exists; refusing to overwrite it" >&2
  exit 1
fi

umask 077
app_secret=$(openssl rand -hex 48)
owner_password=$(openssl rand -hex 32)
runtime_password=$(openssl rand -hex 32)
minio_user="mailer$(openssl rand -hex 8)"
minio_password=$(openssl rand -hex 32)

cat >"$env_file" <<EOF
APP_ENV=production
APP_SECRET_KEY=$app_secret
POSTGRES_OWNER_USER=mailer_owner
POSTGRES_OWNER_PASSWORD=$owner_password
POSTGRES_RUNTIME_USER=mailer_app
POSTGRES_RUNTIME_PASSWORD=$runtime_password
MINIO_ROOT_USER=$minio_user
MINIO_ROOT_PASSWORD=$minio_password
S3_BUCKET=mailer
CORS_ORIGINS=["https://premium-b2b-mailer.vercel.app","https://premium-b2b-mailer-digagency.vercel.app"]
PUBLIC_BASE_URL=https://5.129.234.72/mailer
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=30
SMTP_HOST=mailer-mailpit
SMTP_PORT=1025
SMTP_USE_TLS=false
EMAIL_PROVIDER=smtp
DEFAULT_SENDER_DOMAIN=localhost
NOTIFICATION_FROM_EMAIL=notifications@localhost
WEBHOOK_ALLOW_PRIVATE_URLS=false
EOF

chmod 600 "$env_file"
echo "Created $env_file with production secrets"
