#!/usr/bin/env bash
# DocPilot RN: push secrets to the two Vercel projects, write local .env files, run migrations.
# Run from Git Bash:  bash scripts/setup-env.sh
# Reads (never prints):
#   G:\AI Engineering Journey\.env                                  GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, VOYAGE_API_KEY (optional)
#   G:\Vibe Engineering Apps\.secrets\docpilot-rn-database-url.txt         pooled Neon URL (API)
#   G:\Vibe Engineering Apps\.secrets\docpilot-rn-database-direct-url.txt  direct Neon URL (migrations, ingestion)
#   G:\Vibe Engineering Apps\.secrets\docpilot-rn-cron-secret.txt          (kept for a future cron route)
#   optional: docpilot-rn-github-token.txt, docpilot-rn-voyage-api-key.txt,
#             docpilot-rn-langfuse-public.txt / -secret.txt, docpilot-rn-ip-hash-salt.txt (created if missing)
# Vercel projects: docpilot-rn-api (repository root) and docpilot-rn (root directory web/).
set -euo pipefail
export PATH="/c/tools/node24:$PATH"
cd "$(dirname "$0")/.."

SECRETS="/g/Vibe Engineering Apps/.secrets"
JOURNEY_ENV="/g/AI Engineering Journey/.env"
API_URL="https://docpilot-rn-api.vercel.app"
WEB_URL="https://docpilotrn.vercel.app"

read_env() { grep -E "^\s*$2\s*=" "$1" | head -1 | sed -E "s/^\s*$2\s*=\s*//; s/^[\"']//; s/[\"']\s*$//" | tr -d '\r'; }
read_secret() { tr -d '\r\n' < "$1"; }
opt_secret() { [ -s "$1" ] && read_secret "$1" || true; }
set_env() { # dir name value [--sensitive]
  local dir="$1" name="$2" value="$3" flag="${4:-}"
  [ -n "$value" ] || { echo "  skip $name (empty)"; return 0; }
  for target in production preview development; do
    local ok=0
    for attempt in 1 2 3 4; do
      if printf '%s' "$value" | (cd "$dir" && vercel env add "$name" "$target" --force $flag >/dev/null 2>&1); then ok=1; break; fi
      sleep $((5 * attempt))
    done
    [ "$ok" = 1 ] || { echo "FAILED: vercel env add $name $target in $dir"; exit 1; }
  done
  echo "  set $name ($dir)"
}

echo "Collecting values..."
GEMINI=$(read_env "$JOURNEY_ENV" GEMINI_API_KEY)
GROQ=$(read_env "$JOURNEY_ENV" GROQ_API_KEY)
OPENROUTER=$(read_env "$JOURNEY_ENV" OPENROUTER_API_KEY)
VOYAGE=$(read_env "$JOURNEY_ENV" VOYAGE_API_KEY || true)
[ -n "$VOYAGE" ] || VOYAGE=$(opt_secret "$SECRETS/docpilot-rn-voyage-api-key.txt")
DB_URL=$(read_secret "$SECRETS/docpilot-rn-database-url.txt")
DIRECT_URL=$(read_secret "$SECRETS/docpilot-rn-database-direct-url.txt")
case "$DB_URL" in postgres*) ;; *) echo "database url must be postgres://"; exit 1;; esac
GH_TOKEN_VAL=$(opt_secret "$SECRETS/docpilot-rn-github-token.txt")
LF_PUBLIC=$(opt_secret "$SECRETS/docpilot-rn-langfuse-public.txt")
LF_SECRET=$(opt_secret "$SECRETS/docpilot-rn-langfuse-secret.txt")
[ -s "$SECRETS/docpilot-rn-ip-hash-salt.txt" ] || openssl rand -hex 16 | tr -d '\r\n' > "$SECRETS/docpilot-rn-ip-hash-salt.txt"
SALT=$(read_secret "$SECRETS/docpilot-rn-ip-hash-salt.txt")
# The corpus was embedded with this provider; the API must embed queries with the same one.
PROVIDER=gemini; DIMS=768
if [ -n "$VOYAGE" ]; then echo "  note: VOYAGE_API_KEY found; the API keeps EMBEDDING_PROVIDER=gemini until the corpus is re-embedded"; fi

echo "Pushing API env (project docpilot-rn-api, repo root)..."
set_env . DATABASE_URL "$DB_URL" --sensitive
set_env . GROQ_API_KEY "$GROQ" --sensitive
set_env . GEMINI_API_KEY "$GEMINI" --sensitive
set_env . OPENROUTER_API_KEY "$OPENROUTER" --sensitive
set_env . VOYAGE_API_KEY "$VOYAGE" --sensitive
set_env . EMBEDDING_PROVIDER "$PROVIDER"
set_env . EMBEDDING_DIMENSIONS "$DIMS"
set_env . GITHUB_TOKEN "$GH_TOKEN_VAL" --sensitive
set_env . LANGFUSE_PUBLIC_KEY "$LF_PUBLIC"
set_env . LANGFUSE_SECRET_KEY "$LF_SECRET" --sensitive
set_env . WEB_ORIGIN "$WEB_URL,http://localhost:3600,http://localhost:3000"
set_env . IP_HASH_SALT "$SALT" --sensitive

echo "Pushing web env (project docpilot-rn, root dir web/)..."
set_env web NEXT_PUBLIC_API_URL "$API_URL"
set_env web NEXT_PUBLIC_APP_URL "$WEB_URL"

echo "Writing .env (API)..."
cat > .env <<ENV
DATABASE_URL=$DB_URL
DATABASE_DIRECT_URL=$DIRECT_URL
GROQ_API_KEY=$GROQ
GEMINI_API_KEY=$GEMINI
OPENROUTER_API_KEY=$OPENROUTER
VOYAGE_API_KEY=$VOYAGE
EMBEDDING_PROVIDER=$PROVIDER
EMBEDDING_DIMENSIONS=$DIMS
GITHUB_TOKEN=$GH_TOKEN_VAL
LANGFUSE_PUBLIC_KEY=$LF_PUBLIC
LANGFUSE_SECRET_KEY=$LF_SECRET
WEB_ORIGIN=http://localhost:3600,http://localhost:3000
PORT=7861
ENV
# web/ is owned by the web app's own setup; locally it needs NEXT_PUBLIC_API_URL=http://localhost:7861.

echo "Running database migrations (direct URL)..."
DATABASE_URL="$DIRECT_URL" EMBEDDING_DIMENSIONS="$DIMS" uv run migrate 2>&1 | tail -3
echo "GitHub Actions secrets for .github/workflows/ingest.yml (set once):"
echo "  gh secret set DATABASE_URL < \"$SECRETS/docpilot-rn-database-direct-url.txt\""
echo "  gh secret set GEMINI_API_KEY   (paste the key)"
echo "Done. Deploy with: vercel deploy --prod --yes   (repo root = API)   and   (cd web && vercel deploy --prod --yes)"
