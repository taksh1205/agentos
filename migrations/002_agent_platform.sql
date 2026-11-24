-- Store.__init__ applies these idempotent additions in the same DDL transaction.
-- Run: python -m agentos.migrate --legacy-documents
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied FLOAT NOT NULL);
CREATE TABLE IF NOT EXISTS budgets(workspace TEXT NOT NULL,run_id TEXT NOT NULL,tokens INTEGER NOT NULL,cost FLOAT NOT NULL,PRIMARY KEY(workspace,run_id));
CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,run_id TEXT NOT NULL,step TEXT NOT NULL,tool TEXT NOT NULL,args TEXT NOT NULL,digest TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS effects(approval_id TEXT PRIMARY KEY,workspace TEXT NOT NULL,tool TEXT NOT NULL,result TEXT NOT NULL,created FLOAT NOT NULL);
CREATE TABLE IF NOT EXISTS inventory(workspace TEXT NOT NULL,sku TEXT NOT NULL,quantity INTEGER NOT NULL,threshold INTEGER NOT NULL,PRIMARY KEY(workspace,sku));
CREATE TABLE IF NOT EXISTS invoices(workspace TEXT NOT NULL,number TEXT NOT NULL,amount FLOAT NOT NULL,paid INTEGER NOT NULL,due TEXT NOT NULL,PRIMARY KEY(workspace,number));
CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,run_id TEXT,kind TEXT NOT NULL,payload TEXT NOT NULL,created FLOAT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,input TEXT NOT NULL,status TEXT NOT NULL,lease FLOAT NOT NULL,attempts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits(id TEXT PRIMARY KEY,bucket INTEGER NOT NULL,count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rag_sources(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,source TEXT NOT NULL,content TEXT NOT NULL,digest TEXT NOT NULL,metadata TEXT NOT NULL,UNIQUE(workspace,source));
CREATE TABLE IF NOT EXISTS rag_chunks(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,workspace TEXT NOT NULL,source TEXT NOT NULL,content TEXT NOT NULL,embedding TEXT NOT NULL,namespace TEXT NOT NULL,metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS semantic_memory(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,content TEXT NOT NULL,embedding TEXT NOT NULL,namespace TEXT NOT NULL,provenance TEXT NOT NULL,expires FLOAT NOT NULL,UNIQUE(workspace,content));
CREATE INDEX IF NOT EXISTS rag_chunks_tenant ON rag_chunks(workspace,namespace);
CREATE INDEX IF NOT EXISTS memory_tenant ON semantic_memory(workspace,expires);
-- PostgreSQL only: CREATE EXTENSION IF NOT EXISTS vector;
-- ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS vec vector;
-- The retrieval service creates dimension/model-specific HNSW expression indexes.
