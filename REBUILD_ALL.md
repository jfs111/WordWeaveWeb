# 🔄 Word Weave Web — Rebuild Guide

## Rebuild a single service (after modifying a file)

```powershell
# 1. Copy the modified file
copy <file> services\<service>\<path>

# 2. Rebuild only the affected service
docker-compose build --no-cache service-a   # Storage (Qdrant)
docker-compose build --no-cache service-b   # Intelligence (Embedding, Clustering, LLM)
docker-compose build --no-cache service-c   # Orchestrator (Web UI, API)

# 3. Restart
docker-compose up -d
```

## Full rebuild (no data loss)

```powershell
docker-compose down
docker-compose build --no-cache
docker-compose up -d
docker-compose ps
```

## Full reset (deletes all data!)

```powershell
docker-compose down
docker volume rm wordweaveweb_postgres_data wordweaveweb_qdrant_data wordweaveweb_document_storage wordweaveweb_redis_data
docker-compose build --no-cache
docker-compose up -d
docker-compose ps
```

⚠️ After a full reset, verify that `docker/init.sql` contains the correct jobs constraint:
```sql
type VARCHAR(50) NOT NULL CHECK (type IN (
    'ingest', 'cluster', 'clustering', 'relations',
    'full_pipeline', 'full_analysis', 'document_analysis'
)),
```

## Change the LLM (no rebuild needed)

```powershell
# Edit docker-compose.yml: LLM_URL and LLM_MODEL
docker-compose up -d
```

## Quick fix for jobs constraint (without reset)

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "ALTER TABLE jobs DROP CONSTRAINT jobs_type_check; ALTER TABLE jobs ADD CONSTRAINT jobs_type_check CHECK (type IN ('ingest', 'cluster', 'clustering', 'relations', 'full_pipeline', 'full_analysis', 'document_analysis'));"
```

## File → Service mapping

| Modified file | Service to rebuild |
|--------------|-------------------|
| `services/service_a/app/api/storage.py` | `service-a` |
| `services/service_a/app/services/qdrant_manager.py` | `service-a` |
| `services/service_b/app/services/clusterer.py` | `service-b` |
| `services/service_b/app/services/relation_detector.py` | `service-b` |
| `services/service_b/app/services/embedder.py` | `service-b` |
| `services/service_c/app/api/chat.py` | `service-c` |
| `services/service_c/app/api/analysis.py` | `service-c` |
| `services/service_c/app/api/doc_analysis.py` | `service-c` |
| `services/service_c/app/templates/project.html` | `service-c` |
| `services/service_c/app/static/css/style.css` | `service-c` |
| `shared/models/orm.py` | **All 3** |
| `shared/config/database.py` | **All 3** |
| `docker/init.sql` | Full reset |
| `docker-compose.yml` | `docker-compose up -d` |

## Post-rebuild verification

```powershell
# Are all services healthy?
docker-compose ps

# Is the fix deployed?
docker exec graphrag-storage cat /app/app/api/storage.py | findstr "batch_ids"
docker exec graphrag-intelligence cat /app/app/services/clusterer.py | findstr "n_init"
docker exec graphrag-orchestrator cat /app/app/api/chat.py | findstr "timeout"

# Is data intact?
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "SELECT 'docs' as t, COUNT(*) FROM documents UNION ALL SELECT 'chunks', COUNT(*) FROM chunks UNION ALL SELECT 'relations', COUNT(*) FROM relations;"
```