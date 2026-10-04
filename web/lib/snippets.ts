/**
 * API and ingestion snippets for /docs. Single source for the web app: keep
 * these in step with the repository README and spec §6.
 */

export function curlVersions(api: string) {
  return `curl -s ${api}/api/versions
# -> {"sources":[{"name":"expo","embedding_model":"...",
#      "versions":[{"version":"v58.0.0","chunk_count":6184,"ingested_at":"...","commit_sha":"..."}]}]}`;
}

export function curlAsk(api: string) {
  return `# Server-Sent Events over a POST: -N turns off buffering so events print as they arrive
curl -N -X POST ${api}/api/ask \\
  -H 'Content-Type: application/json' \\
  -H 'Accept: text/event-stream' \\
  -d '{"question":"How do I schedule a local notification?","sdk":"expo","version":"v58.0.0","mode":"answer"}'`;
}

export const streamExample = `id: 1
data: {"kind":"retrieval","chunks":[{"id":"c_8f12a0","n":1,"title":"scheduleNotificationAsync(request)","heading_path":"Notifications › API › ...","url":"https://docs.expo.dev/versions/v58.0.0/sdk/notifications/#...","version":"v58.0.0","score":0.912,"snippet":"Schedules a notification..."}]}

id: 2
data: {"kind":"token","text":"To schedule a local notification, call "}

id: 87
data: {"kind":"citations","verified":[{"n":1,"chunk_id":"c_8f12a0","url":"...","quote":"..."}],"removed":[{"n":7,"reason":"..."}],"unsupported":false}

id: 88
data: {"kind":"done","question_id":"...","latency_ms":2840,"usage":{"prompt_tokens":4210,"completion_tokens":412,"usd":0.00091}}`;

export function curlDiff(api: string) {
  return `# What changed? between two versions: adds a {"kind":"diff"} event with the structured diff
curl -N -X POST ${api}/api/ask \\
  -H 'Content-Type: application/json' \\
  -d '{"question":"How do I show notifications in the foreground?","sdk":"expo",
       "version":"v58.0.0","compare_version":"v57.0.0","mode":"diff"}'`;
}

export function curlQuestion(api: string) {
  return `# A stored answer (what /q/<id> renders)
curl -s ${api}/api/questions/<question id>

# Feedback: recorded, not acted on
curl -s -X POST ${api}/api/questions/<question id>/feedback \\
  -H 'Content-Type: application/json' -d '{"feedback":"up"}'`;
}

export const ingestCommands = `# From the repository root (Python 3.12+, uv). DATABASE_URL points at Neon with pgvector.
uv sync
uv run ingest expo --version v58.0.0     # one Expo SDK version
uv run ingest expo --version v57.0.0
uv run ingest expo --version unversioned # guides, EAS, Router (searched with every version)
uv run ingest react-native               # current React Native docs

# Re-running is idempotent: chunks are upserted by content hash, embeddings cached.`;

export const evalCommands = `uv run evals --config hybrid_rerank   # writes docs/evals.md with the results table
uv run evals --config vector          # compare retrieval configurations`;
