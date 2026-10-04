# HTTP API

Interactive reference: **`/api/docs`** (OpenAPI 3, generated from the Pydantic models in
[`api/schemas.py`](../src/docpilot/api/schemas.py); raw schema at `/api/openapi.json`).
This page is the contract the web app (`web/lib/api.ts`) codes against.

Base URLs: production `https://docpilot-rn-api.vercel.app`, local `http://localhost:7861`.

```
GET  /api/versions                     sources, versions, chunk counts, embedding model
POST /api/ask                          SSE: retrieval -> token* -> (diff) -> citations -> done | error
GET  /api/questions/{id}               the stored question (share links /q/[id])
POST /api/questions/{id}/feedback      { "feedback": "up" | "down" }
GET  /api/health                       db, corpus freshness and vector coverage, providers
```

## Errors before a stream starts

Every error response is `{"detail": {"code", "message", "retry_after"?, "field"?}}`.

| Status | `code` | When |
|---|---|---|
| 422 | `invalid_input` | Body failed validation (`field` names it: `question`, `version`, `compare_version`, `mode`, `thread`...). Question 1-1,000 characters; `diff` needs a different `compare_version` and `sdk: "expo"`. |
| 404 | `version_not_found` | No corpus for that `sdk`/`version` (`field: "version"`). |
| 404 | `question_not_found` | Unknown question id (GET or feedback). |
| 429 | `rate_limited` | 30 questions per hour per client IP. `retry_after` (seconds) in the body **and** a `Retry-After` header. |
| 503 | `unavailable` | Database unreachable before the stream could start. |

CORS: origins from `WEB_ORIGIN`; methods `GET, POST, OPTIONS`; request headers
`Content-Type, Accept, Authorization, Last-Event-ID`; `Retry-After` is exposed.

## `GET /api/versions`

```jsonc
{
  "sources": [
    {
      "name": "expo",                 // the sdk id used in /api/ask
      "label": "Expo",
      "repo": "expo/expo", "licence": "MIT",
      "attribution_url": "https://github.com/expo/expo/tree/main/docs",
      "embedding_model": "gemini-embedding-001",
      "default_version": "v58.0.0",   // newest pickable version
      "versions": [                   // newest first; "unversioned" last
        { "version": "v58.0.0", "label": "SDK 58", "chunk_count": 877, "document_count": 249,
          "embedded_count": 877,          // chunks with a vector (< chunk_count while partial)
          "commit_sha": "0e8f35c5…", "ingested_at": "2026-10-05T…Z",
          "embedding_model": "gemini-embedding-001", "dimensions": 768, "shared": false },
        { "version": "v57.0.0", "label": "SDK 57", … , "shared": false },
        { "version": "unversioned", "label": "Guides (all versions)", … , "shared": true }
      ]
    },
    { "name": "react-native", "label": "React Native", "repo": "react/react-native-website",
      "licence": "CC-BY-4.0", "default_version": "current",
      "versions": [ { "version": "current", "label": "Current", … } ] }
  ]
}
```

`unversioned` (the Expo guides) is searched together with whichever SDK version is picked
and is never picked on its own; the UI hides it. React Native has one version, so diff
mode is Expo-only.

## `POST /api/ask`

```jsonc
{
  "question": "How do I keep the splash screen visible while loading data?",  // 1-1,000 chars
  "sdk": "expo",                      // "expo" | "react-native"
  "version": "v58.0.0",
  "mode": "answer",                   // "answer" | "diff"
  "compare_version": "v57.0.0",       // diff mode only
  "thread": [                         // optional: up to 8 messages, oldest first; only used
    { "role": "user", "content": "…" },      // to rewrite a follow-up into a standalone
    { "role": "assistant", "content": "…" }  // search query (extra are dropped, oldest first)
  ]
}
```

Response: `200 text/event-stream`, unbuffered (`Cache-Control: no-cache, no-transform`,
`X-Accel-Buffering: no`, no compression). Every message is **unnamed** with an `id:` line
(1, 2, 3...) and one JSON object whose `kind` names the event:

```
id: 1
data: {"kind":"retrieval", ...}

id: 2
data: {"kind":"token","text":"Call "}
```

It is a POST, so read it with `fetch` + a stream reader (EventSource is GET-only). The
question is stored before the first event, so after a dropped connection the result is
available at `GET /api/questions/{question_id}` (the id is in the first event).

### `retrieval` (always first)

```jsonc
{
  "kind": "retrieval",
  "question_id": "57666f0c-…",
  "rewritten": null,                       // the standalone query when `thread` was used
  "config": "hybrid",                      // what actually ran: hybrid_rerank | hybrid | fulltext
  "versions": ["v58.0.0", "unversioned"],  // diff mode: [older, newer]
  "before_version": "v57.0.0", "after_version": "v58.0.0",   // diff mode only
  "chunks": [
    {
      "n": 1,                              // exactly the [n] the answer cites; unique, 1..N
      "id": "5f0c…",                       // chunk id
      "sdk": "expo",
      "version": "v58.0.0",                // real version string; guides are "unversioned"
      "title": "SplashScreen",
      "heading_path": "SplashScreen › Usage › Delay hiding the splash screen",
      "url": "https://docs.expo.dev/versions/v58.0.0/sdk/splash-screen/#delay-hiding-the-splash-screen",
      "kind": "prose",                     // prose | code | table
      "score": 0.0331,                     // final score of the stage that ordered it
      "scores": { "vector": 0.71, "vector_rank": 2, "fulltext": 0.05, "fulltext_rank": 1,
                  "rrf": 0.0325, "boost": 0.0 },
      "snippet": "### Delay hiding the splash screen\n\nIn some cases…"  // the FULL passage
    }                                      // the model saw and the verifier checked
  ]
}
```

In diff mode passages of the older version come first (`n` 1..k), then the newer one
(`n` k+1..N). The unversioned guides are left out of a diff.

### `token` (zero or more)

`{"kind": "token", "text": "…"}`: raw model output deltas, unverified. Diff mode streams
the prose rendered from the structured diff, one line per event.

### `diff` (diff mode only, before the tokens)

```jsonc
{
  "kind": "diff",
  "diff": {
    "summary": "SDK 58 adds an Android sensitive flag … [6]",
    "changes": [
      { "kind": "added",                  // added | removed | renamed | behaviour
        "subject": "`android.isSensitive` option for setStringAsync / setImageAsync",
        "before": null, "after": "Set android.isSensitive …",
        "citations": [6] }                // only numbers that exist in retrieval.chunks
    ],
    "missing": null,
    "before_version": "v57.0.0", "after_version": "v58.0.0"   // older -> newer, always
  },
  "dropped_changes": 0                   // changes removed because no citation was valid
}
```

### `citations` (after the last token)

```jsonc
{
  "kind": "citations",
  "answer": "…",                           // the rendered answer: invalid [n] removed.
                                           // Show this instead of the concatenated tokens.
  "citations": {
    "verified": [
      { "n": 1, "chunk_id": "5f0c…", "url": "…", "title": "…", "heading_path": "…",
        "version": "v58.0.0",
        "quote": "you can use `preventAutoHideAsync()` to manually control when …",
        "quote_source": "overlap" }        // "answer": the model quoted it and it was found;
    ],                                     // "overlap": best-matching passage sentence.
    "removed": [ { "n": 9, "reason": "no passage with this number" } ],
    "unsupported": false                   // true: no verified citation at all
  },
  "verification": { "status": "supported", "unsupported": false, "refused": false,
                    "emitted": 3, "verified": 3, "removed": 0, "precision": 1.0,
                    "quotes_checked": 1, "quotes_verified": 1, "uncited_quotes": 0 }
}
```

`quote` is always verbatim text from that chunk's `snippet` (matching ignores case,
whitespace and curly quotes), so the source panel can highlight it. `status` is
`supported`, `partial` (some citations removed) or `unsupported`. `refused` is true when
the answer starts with the "I couldn't find this in the … docs" sentence the prompt
requires for unanswerable questions.

### `done` (last)

```jsonc
{
  "kind": "done",
  "question_id": "57666f0c-…",            // always present: share link + feedback
  "latency_ms": 9608,
  "usage": {
    "prompt_tokens": 4504, "completion_tokens": 504, "reasoning_tokens": 12,
    "total_tokens": 5008,
    "usd": 0.00098,                        // at paid rates: model + query embedding + rerank
    "llm_usd": 0.000978, "retrieval_usd": 0.0000021,
    "calls": 1, "failed_calls": 0,
    "served_by": ["openai/gpt-oss-120b"],  // or "gemini-3.5-flash-lite" after a fallback
    "by_model": [ … ]
  }
}
```

### `error` (instead of the remaining events)

`{"kind": "error", "code": "unavailable" | "stream" | "version_not_found" | "server",
"message": "…", "question_id": "…"}`. `unavailable`: every model route is rate-limited
or down; `stream`: the model failed after tokens were sent (ask again). The question row
is stored with `status: "failed"`.

## `GET /api/questions/{id}`

```jsonc
{
  "id": "…", "created_at": "…", "question": "…", "sdk": "expo", "version": "v58.0.0",
  "compare_version": null, "mode": "answer", "status": "done", "rewritten": null,
  "answer": "…",                            // the rendered (verified) answer
  "chunks": [ … ],                          // same shape as retrieval.chunks, incl. snippet
  "citations": { "verified": [ … ], "removed": [ … ], "unsupported": false },
  "verification": { … },                    // as in the citations event, plus "prompt"
  "diff": null,                             // the diff object in diff mode
  "usage": { … }, "latency_ms": 9608, "feedback": null, "error": null
}
```

## `POST /api/questions/{id}/feedback`

`{"feedback": "up" | "down"}` -> `{"id": "…", "feedback": "up"}`. Recorded, not acted on
(spec section 3).

## `GET /api/health`

```jsonc
{
  "ok": true, "version": "0.1.0", "db": true, "store": "postgres",
  "providers": { "groq": true, "gemini": true, "voyage": false },
  "embedding": { "provider": "gemini", "model": "gemini-embedding-001", "dimensions": 768 },
  "rerank": false,
  "corpora": [ { "sdk": "expo", "version": "v58.0.0", "chunk_count": 877, "embedded_count": 877,
                 "commit_sha": "…", "ingested_at": "…", "age_days": 0.2, "stale": false } ]
}
```

`stale` turns true after `CORPUS_MAX_AGE_DAYS` (45). `embedded_count` is the vector
coverage; while a corpus is only partly embedded, retrieval still works (full-text covers every chunk; vectors cover the embedded
ones), and when the query embedding itself fails (quota) hybrid degrades to full-text.
