-- Graph-RAG Multi-Tenant — Schema PostgreSQL
-- docker/init.sql

-- ─── Extensions ───
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── OWNERS (utilisateurs) ───
CREATE TABLE owners (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    type VARCHAR(20) DEFAULT 'individual' CHECK (type IN ('individual', 'organization')),
    plan VARCHAR(20) DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'enterprise')),
    api_key VARCHAR(64) UNIQUE,  -- Pour accès API externe (systèmes agentiques)
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── PROJECTS ───
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Config processing
    chunking_size INTEGER DEFAULT 1500,
    chunking_overlap INTEGER DEFAULT 200,
    embedding_model VARCHAR(100) DEFAULT 'paraphrase-multilingual-MiniLM-L12-v2',
    clustering_method VARCHAR(50) DEFAULT 'auto-k',
    similarity_threshold FLOAT DEFAULT 0.6,
    
    -- Quotas
    max_documents INTEGER DEFAULT 100,
    max_storage_mb INTEGER DEFAULT 500,
    
    -- Stats (updated by triggers/services)
    total_documents INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 0,
    total_relations INTEGER DEFAULT 0,
    total_storage_mb FLOAT DEFAULT 0,
    
    -- ChromaDB path
    chromadb_path VARCHAR(500),
    
    -- Status
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'processing', 'archived', 'deleted')),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(owner_id, name)
);

-- ─── DOCUMENTS ───
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    filename VARCHAR(500) NOT NULL,
    title VARCHAR(500),
    category VARCHAR(255),
    subcategory VARCHAR(255),
    
    file_path VARCHAR(1000),       -- Path to original file
    file_size_mb FLOAT DEFAULT 0,
    pages INTEGER DEFAULT 0,
    
    -- Processing status
    status VARCHAR(20) DEFAULT 'uploaded' CHECK (status IN ('uploaded', 'processing', 'processed', 'error')),
    error_message TEXT,
    processed_at TIMESTAMP WITH TIME ZONE,
    
    -- Stats
    total_chunks INTEGER DEFAULT 0,
    total_relations INTEGER DEFAULT 0,
    
    -- Flexible metadata
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── CHUNKS ───
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    chunk_index INTEGER NOT NULL,
    chromadb_id VARCHAR(255) UNIQUE,  -- ID in ChromaDB collection
    
    -- Text content (for quick access without ChromaDB)
    text_preview VARCHAR(500),
    word_count INTEGER DEFAULT 0,
    
    -- Location in source document
    page_start INTEGER,
    page_end INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    
    -- Clustering
    cluster_id INTEGER,
    
    -- Relations
    has_relations BOOLEAN DEFAULT false,
    relation_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── RELATIONS ───
CREATE TABLE relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    chunk_a_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    chunk_b_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    
    type VARCHAR(50) NOT NULL CHECK (type IN (
        'PREREQUIS', 'COMPLEMENTAIRE', 'SIMILAIRE', 'METHODOLOGIQUE',
        'APPLICATION', 'EXEMPLE', 'SUITE_LOGIQUE', 'TRANSVERSAL', 'AUTRE'
    )),
    intensite VARCHAR(20) DEFAULT 'MOYENNE' CHECK (intensite IN ('FAIBLE', 'MOYENNE', 'FORTE')),
    confiance FLOAT DEFAULT 0.5 CHECK (confiance >= 0 AND confiance <= 1),
    similarite_cosinus FLOAT CHECK (similarite_cosinus >= 0 AND similarite_cosinus <= 1),
    
    justification TEXT,
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Prevent duplicate relations
    UNIQUE(project_id, chunk_a_id, chunk_b_id)
);

-- ─── PROJECT MEMBERS (RBAC) ───
CREATE TABLE project_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    
    role VARCHAR(20) NOT NULL DEFAULT 'viewer' CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(project_id, owner_id)
);

-- ─── JOBS (async processing tracking) ───
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    
    type VARCHAR(50) NOT NULL CHECK (type IN (
        'ingest', 'cluster', 'clustering', 'relations',
        'full_pipeline', 'full_analysis', 'document_analysis'
    )),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    
    -- Progress
    progress FLOAT DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    current_step VARCHAR(255),
    
    -- Input/Output
    input_data JSONB DEFAULT '{}',
    output_data JSONB DEFAULT '{}',
    error_message TEXT,
    
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── INDEXES ───
CREATE INDEX idx_projects_owner ON projects(owner_id);
CREATE INDEX idx_documents_project ON documents(project_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_chunks_project ON chunks(project_id);
CREATE INDEX idx_chunks_document ON chunks(document_id);
CREATE INDEX idx_chunks_cluster ON chunks(project_id, cluster_id);
CREATE INDEX idx_chunks_chromadb ON chunks(chromadb_id);
CREATE INDEX idx_relations_project ON relations(project_id);
CREATE INDEX idx_relations_chunks ON relations(chunk_a_id, chunk_b_id);
CREATE INDEX idx_relations_type ON relations(project_id, type);
CREATE INDEX idx_project_members_project ON project_members(project_id);
CREATE INDEX idx_project_members_owner ON project_members(owner_id);
CREATE INDEX idx_jobs_project ON jobs(project_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_owners_api_key ON owners(api_key);

-- ─── UPDATED_AT TRIGGER ───
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_owners_updated_at BEFORE UPDATE ON owners
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER tr_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER tr_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── QUOTAS PAR PLAN ───
COMMENT ON TABLE owners IS 'Quotas: free(3 projects, 100 docs, 500MB) | pro(20, 5000, 50GB) | enterprise(unlimited)';
