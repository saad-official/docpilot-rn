-- 0001_init: the schema from docs/spec.md section 5, plus additions the spec was silent on
-- (each marked ADDED with its reason).
--
-- {{EMBEDDING_DIMENSIONS}} is substituted by `uv run migrate` from the EMBEDDING_DIMENSIONS
-- environment variable (default 768 = gemini-embedding-001 truncated; 1024 = voyage-4-lite).
-- The column is typed because an HNSW index needs a fixed dimension. Switching models is a
-- re-embed: see docs/setup.md, "Switching the embedding model".
--
-- Everything lives in schema `docpilot` so the Neon project can host other apps and
-- `DROP SCHEMA docpilot CASCADE` is a clean uninstall. The `vector` extension is
-- database-wide (it lives in `public`).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS docpilot;

CREATE TABLE IF NOT EXISTS docpilot.sources (
    id              smallserial PRIMARY KEY,
    name            text NOT NULL UNIQUE CHECK (name IN ('expo', 'react-native')),
    repo            text NOT NULL,
    licence         text NOT NULL,
    attribution_url text NOT NULL
);

-- One row per (source, version). A corpus is tied to exactly one embedding model.
CREATE TABLE IF NOT EXISTS docpilot.corpora (
    id              bigserial PRIMARY KEY,
    source_id       smallint NOT NULL REFERENCES docpilot.sources (id) ON DELETE CASCADE,
    version         text NOT NULL,
    commit_sha      text NOT NULL,
    embedding_model text NOT NULL,
    dimensions      integer NOT NULL,
    chunk_count     integer NOT NULL DEFAULT 0,
    document_count  integer NOT NULL DEFAULT 0,      -- ADDED: shown by /api/versions
    stats           jsonb NOT NULL DEFAULT '{}'::jsonb, -- ADDED: last ingestion report
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, version)
);

CREATE TABLE IF NOT EXISTS docpilot.documents (
    id           text PRIMARY KEY,                -- sha1(sdk:version:path), stable
    corpus_id    bigint NOT NULL REFERENCES docpilot.corpora (id) ON DELETE CASCADE,
    path         text NOT NULL,
    url          text NOT NULL,
    title        text NOT NULL,
    description  text,
    platforms    text[] NOT NULL DEFAULT '{}',
    content_hash text NOT NULL,
    UNIQUE (corpus_id, path)
);

CREATE TABLE IF NOT EXISTS docpilot.chunks (
    id           text PRIMARY KEY,                -- sha1(document:anchor:content_hash), stable
    document_id  text NOT NULL REFERENCES docpilot.documents (id) ON DELETE CASCADE,
    corpus_id    bigint NOT NULL REFERENCES docpilot.corpora (id) ON DELETE CASCADE,
    sdk          text NOT NULL,                   -- ADDED: denormalised for the filter
    version      text NOT NULL,
    ordinal      integer NOT NULL,                -- ADDED: position within the page
    title        text NOT NULL,                   -- ADDED: page title, denormalised
    heading_path text NOT NULL,
    anchor       text,
    url          text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('prose', 'code', 'table')),
    content      text NOT NULL,
    tokens       integer NOT NULL,
    content_hash text NOT NULL,
    embedding    vector({{EMBEDDING_DIMENSIONS}}),
    -- English stemming for prose ("installing" matches "install"); heading text weighs more.
    tsv          tsvector GENERATED ALWAYS AS (
                     setweight(to_tsvector('english', title || ' ' || heading_path), 'A')
                     || setweight(to_tsvector('english', content), 'B')) STORED,
    -- ADDED (spec: "API names kept as exact tokens via a simple dictionary"): no stemming,
    -- no stop words, so `useRouter`, `expo-notifications`, `app.json` match exactly.
    tsv_simple   tsvector GENERATED ALWAYS AS (
                     setweight(to_tsvector('simple', title || ' ' || heading_path), 'A')
                     || setweight(to_tsvector('simple', content), 'B')) STORED
);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON docpilot.chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv ON docpilot.chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_tsv_simple ON docpilot.chunks USING gin (tsv_simple);
CREATE INDEX IF NOT EXISTS chunks_corpus_version ON docpilot.chunks (corpus_id, version);
CREATE INDEX IF NOT EXISTS chunks_sdk_version ON docpilot.chunks (sdk, version);

-- ADDED: the embedding cache, keyed by what was embedded. Untyped `vector` so one table
-- serves any model; unchanged text is never embedded twice, and a failed ingestion resumes.
CREATE TABLE IF NOT EXISTS docpilot.embedding_cache (
    content_hash text NOT NULL,
    model        text NOT NULL,
    dimensions   integer NOT NULL,
    embedding    vector NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (content_hash, model, dimensions)
);

CREATE TABLE IF NOT EXISTS docpilot.questions (
    id              uuid PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    sdk             text NOT NULL,
    version         text NOT NULL,
    compare_version text,                         -- ADDED: diff mode's second version
    mode            text NOT NULL CHECK (mode IN ('answer', 'diff')),
    question        text NOT NULL,
    rewritten       text,
    retrieval       jsonb NOT NULL DEFAULT '{}'::jsonb,
    answer          text,
    citations       jsonb NOT NULL DEFAULT '[]'::jsonb,
    verification    jsonb NOT NULL DEFAULT '{}'::jsonb,
    diff            jsonb,                        -- ADDED: the structured DiffAnswer
    usage           jsonb NOT NULL DEFAULT '{}'::jsonb,
    latency_ms      integer,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'done', 'failed')), -- ADDED
    error           text,                         -- ADDED
    feedback        text CHECK (feedback IN ('up', 'down')),
    client_key      text                          -- ADDED: sha256(salt:ip), rate limiting
);
CREATE INDEX IF NOT EXISTS questions_client_recent ON docpilot.questions (client_key, created_at);

CREATE TABLE IF NOT EXISTS docpilot.eval_runs (
    id             uuid PRIMARY KEY,
    golden_version text NOT NULL,
    config         jsonb NOT NULL,
    metrics        jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
