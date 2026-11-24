-- Store bootstrap creates portable tables first. Apply this after table bootstrap.
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS vec vector(384);
CREATE INDEX IF NOT EXISTS documents_vec_hnsw ON documents USING hnsw (vec vector_cosine_ops);
CREATE INDEX IF NOT EXISTS documents_lexical ON documents USING gin(to_tsvector('english',content));
CREATE INDEX IF NOT EXISTS documents_workspace ON documents(workspace);
CREATE INDEX IF NOT EXISTS memories_workspace ON memories(workspace,expires);
