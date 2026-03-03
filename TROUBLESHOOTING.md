# 🔧 Word Weave Web — Troubleshooting Guide

> Based on issues encountered in production. Last updated: 03/03/2026

---

## 📋 Table of Contents

1. [General Diagnostic Commands](#1-general-diagnostic-commands)
2. [Services & Containers](#2-services--containers)
3. [PostgreSQL Database](#3-postgresql-database)
4. [Qdrant & Embeddings](#4-qdrant--embeddings)
5. [Clustering](#5-clustering)
6. [Relation Detection](#6-relation-detection)
7. [Document Analysis](#7-document-analysis)
8. [Web Interface (UI)](#8-web-interface-ui)
9. [Local LLM](#9-local-llm)
10. [Full Reset](#10-full-reset)

---

## 1. General Diagnostic Commands

### Check the status of all services

```powershell
docker-compose ps
```

All services should be `Up` and `healthy`:
- `graphrag-storage` (Service A — Qdrant, storage)
- `graphrag-intelligence` (Service B — Embedding, Clustering, LLM)
- `graphrag-orchestrator` (Service C — API, Web UI)
- `graphrag-postgres` (PostgreSQL)
- `graphrag-redis` (Redis cache)
- `graphrag-qdrant` (Qdrant)

### View service logs (without health check noise)

```powershell
# Service A (Storage)
docker logs graphrag-storage --tail 30 2>&1 | findstr /v "health"

# Service B (Intelligence)
docker logs graphrag-intelligence --tail 30 2>&1 | findstr /v "health"

# Service C (Orchestrator / Web UI)
docker logs graphrag-orchestrator --tail 30 2>&1 | findstr /v "health"

# Alternative with Select-String (more reliable on PowerShell)
docker logs graphrag-orchestrator 2>&1 | Select-String "Error|error|500|Traceback"
```

### Check Docker volumes

```powershell
docker volume ls | findstr wordweaveweb
```

Expected volumes:
- `wordweaveweb_postgres_data`
- `wordweaveweb_qdrant_data`
- `wordweaveweb_document_storage`
- `wordweaveweb_redis_data`

---

## 2. Services & Containers

### Problem: Service won't start

**Symptom**: `docker-compose ps` shows a service as `Exited` or `Restarting`

**Diagnosis**:
```powershell
docker logs <container-name> --tail 50
```

**Common causes**:
- Port already in use → stop the other process
- Dependency unavailable (postgres not ready) → restart with `docker-compose up -d`
- Python syntax error → check recently modified files

### Problem: Build fails with pip timeout

**Symptom**: `ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org')`

**Solution**: Retry — this is a temporary network issue:
```powershell
docker-compose build --no-cache <service-name>
```

### Problem: Docker Desktop not running

**Symptom**: `error during connect: Head "http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/_ping"`

**Solution**: Open Docker Desktop, wait for the green icon, then retry the command.

### Full rebuild of a service

```powershell
copy <modified_file> services\<service>\<path>
docker-compose build --no-cache <service-name>
docker-compose up -d
```

Services:
| Service | Docker Name | Build |
|---------|-----------|-------|
| Service A | service-a | `docker-compose build --no-cache service-a` |
| Service B | service-b | `docker-compose build --no-cache service-b` |
| Service C | service-c | `docker-compose build --no-cache service-c` |

---

## 3. PostgreSQL Database

### Check data in the database

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
SELECT 'owners' as t, COUNT(*) FROM owners
UNION ALL SELECT 'projects', COUNT(*) FROM projects
UNION ALL SELECT 'documents', COUNT(*) FROM documents
UNION ALL SELECT 'chunks', COUNT(*) FROM chunks
UNION ALL SELECT 'relations', COUNT(*) FROM relations
UNION ALL SELECT 'jobs', COUNT(*) FROM jobs;
"
```

### Check CHECK constraints

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
SELECT tc.table_name, tc.constraint_name, cc.check_clause
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc ON tc.constraint_name = cc.constraint_name
WHERE tc.constraint_type = 'CHECK' AND tc.table_schema = 'public'
ORDER BY tc.table_name;
"
```

### Problem: `violates check constraint "jobs_type_check"`

**Symptom**: `CheckViolationError: new row for relation "jobs" violates check constraint "jobs_type_check"`

**Cause**: `init.sql` doesn't include all job types. Required types: `ingest`, `cluster`, `clustering`, `relations`, `full_pipeline`, `full_analysis`, `document_analysis`.

**Immediate fix** (without reset):
```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
ALTER TABLE jobs DROP CONSTRAINT jobs_type_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_type_check CHECK (type IN (
    'ingest', 'cluster', 'clustering', 'relations',
    'full_pipeline', 'full_analysis', 'document_analysis'
));
"
```

**Permanent fix**: Update `docker/init.sql` with the correct types.

### Check job status

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
SELECT id, type, status, progress, current_step, error_message
FROM jobs ORDER BY created_at DESC LIMIT 10;
"
```

### Clean up stuck jobs

```powershell
# Delete a specific job
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
DELETE FROM jobs WHERE id='<job-id>';
"

# Delete all stuck jobs of a given type
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
DELETE FROM jobs WHERE type='document_analysis' AND status='running';
"
```

### Delete a document in error state

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
DELETE FROM documents WHERE status='error' AND filename='<filename>';
"
```

---

## 4. Qdrant & Embeddings

### Problem: `500 Internal Server Error` on `/embeddings`

**Symptom**: Clustering or relation detection fails with a 500 error on the embeddings endpoint.

**Diagnosis**:
```powershell
docker logs graphrag-storage 2>&1 | Select-String "Embeddings|Error|Qdrant"
```

**Cause 1**: Qdrant is not ready or the collection doesn't exist yet.

**Solution**: Verify the Qdrant container is healthy:
```powershell
docker-compose ps qdrant
curl http://localhost:6333/collections
```

**Cause 2**: The endpoint doesn't return enough data (pagination issue).

**Solution**: `qdrant_manager.py` uses batch scrolling. Verify the fetch works:
```powershell
docker exec graphrag-storage cat /app/app/services/qdrant_manager.py | findstr "scroll\|batch"
```

### Verify the fix is deployed

```powershell
docker exec graphrag-storage cat /app/app/api/storage.py | findstr "batch_size\|Fetch all\|batch_ids"
```

### Check item count in Qdrant

```powershell
docker logs graphrag-storage 2>&1 | Select-String "Qdrant.*items\|Qdrant.*points"
curl http://localhost:6333/collections
```

---

## 5. Clustering

### Check clustering results

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
SELECT cluster_id, COUNT(*) as chunks, COUNT(*)*(COUNT(*)-1)/2 as max_pairs
FROM chunks
WHERE project_id='<project-id>' AND cluster_id IS NOT NULL
GROUP BY cluster_id ORDER BY chunks DESC;
"
```

### Problem: Too few clusters (e.g., 4 instead of 30+)

**Symptom**: Auto-K produces very few clusters despite many chunks.

**Diagnosis**:
```powershell
docker logs graphrag-intelligence --tail 30 2>&1 | Select-String "Auto-K|Clustering|Received"
```

**Cause 1**: The `/embeddings` endpoint only returns a few items (e.g., 14 instead of 415). Check the logs:
```powershell
docker logs graphrag-storage 2>&1 | Select-String "Embeddings.*Returning"
```
→ If the returned count is low, it's a Qdrant issue (see section 4).

**Cause 2**: The Silhouette score (weight 0.4) favors fewer clusters. Auto-K tests K from `√(N/2)` to `2×√N`.

**Auto-K parameters** (in `clusterer.py`):
- `n_init=20`: Number of KMeans runs per K tested
- `max_iter=300`: Max iterations per run
- Weighting: `elbow×0.3 + silhouette×0.4 + davies_bouldin×0.3`

### Check detailed Auto-K logs

```powershell
docker logs graphrag-intelligence 2>&1 | Select-String "Auto-K"
```

Expected output example:
```
[Auto-K] n=415, testing K range: [14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40]
[Auto-K] K=14: silhouette=0.0344, DB=1.7234, inertia=890.2
...
[Auto-K] RESULT: elbow=36, silhouette=28, DB=38 → optimal=34
```

---

## 6. Relation Detection

### Estimate processing time

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
SELECT cluster_id, COUNT(*) as chunks, COUNT(*)*(COUNT(*)-1)/2 as max_pairs
FROM chunks WHERE project_id='<project-id>' AND cluster_id IS NOT NULL
GROUP BY cluster_id ORDER BY chunks DESC;
"
```

Estimate: ~1 second per LLM call, cap of 500 pairs per cluster, cosine filter ≥ 0.6.

| Chunks/cluster | Max pairs | After filter (~) | Estimated time |
|---------------|-----------|-----------------|---------------|
| 70+ | 2500 → 500 | ~400-500 | 5-8 min |
| 40-50 | 800-1200 → 500 | ~300-500 | 4-6 min |
| 20-30 | 200-400 | ~150-300 | 2-4 min |
| < 15 | < 100 | ~50-80 | < 1 min |

### Problem: Relations fail with 500

**Diagnosis**: Same root cause as clustering — the `/embeddings` endpoint doesn't return enough data.

**Check**:
```powershell
docker logs graphrag-storage 2>&1 | Select-String "Embeddings"
```

### Track progress in real time

The UI displays progress. Alternatively, check the database:
```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
SELECT type, status, progress, current_step FROM jobs
WHERE type='relations' ORDER BY created_at DESC LIMIT 1;
"
```

---

## 7. Document Analysis

### Problem: Pipeline stuck at 30% (`assignation_clusters`)

**Symptom**: The job stays at `running / 30% / assignation_clusters` without progressing.

**Diagnosis**:
```powershell
docker logs graphrag-orchestrator 2>&1 | Select-String "DocAnalysis|Task|crashed"
```

**Possible causes**:
1. `asyncio.create_task` crashes silently → Check the `_safe_run` wrapper
2. The embeddings endpoint returns 500 → See section 4
3. The LLM is disconnected → Check LM Studio

**Solution**: Clean up the stuck job and retry:
```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
DELETE FROM jobs WHERE type='document_analysis' AND status='running';
"
```

### Problem: `Unexpected token 'I', "Internal S"...`

**Symptom**: The UI shows a JSON error instead of launching the analysis.

**Cause**: The server returns a 500 before even creating the job (usually `jobs_type_check`).

**Diagnosis**:
```powershell
docker logs graphrag-orchestrator 2>&1 | Select-String "analyze|CheckViolation|jobs_type"
```

**Solution**: See section 3 — fix the `jobs_type_check` constraint.

---

## 8. Web Interface (UI)

### Problem: Stats show 0 after refresh

**Cause 1**: Duplicate JavaScript variables → `SyntaxError: Identifier 'currentJobId' has already been declared`

**Diagnosis**: Open the console (F12) and look for red errors.

**Solution**: Verify there are no duplicate `let` declarations in `project.html`:
```powershell
docker exec graphrag-orchestrator cat /app/app/templates/project.html | findstr "let currentJobId"
```
→ Should appear only ONCE.

**Cause 2**: The `/stats` endpoint uses cached counters from the `projects` table instead of real COUNTs.

**Solution**: The `analysis.py` endpoint should use real `SELECT COUNT(*)` queries on `documents`, `chunks`, `relations`.

### Problem: Page doesn't update automatically

**Solution**: Automatic polling (every 5 seconds) must be enabled in `init()`:
```javascript
setInterval(async () => {
    await loadStats();
    updateStepper();
    loadDocuments();
}, 5000);
```

### Problem: Search fails with `httpx.ReadTimeout`

**Cause**: The default timeout is too short for the first request (model loading).

**Solution**: Increase timeouts in `chat.py`:
```python
async with httpx.AsyncClient(timeout=60) as client:
```

### Debug via browser console

1. F12 → Console
2. Type `allow pasting` + Enter
3. Test the API:
```javascript
fetch(`/projects/${PROJECT_ID}/stats`, {
    headers: {'Authorization': `Bearer ${TOKEN}`}
}).then(r=>r.json()).then(d=>console.log('STATS:', d))
```

---

## 9. Local LLM

### Check LLM connection

The UI displays "LLM connected" or "LLM disconnected". To test manually:
```powershell
curl http://localhost:1234/v1/models
```

### Problem: LLM disconnected

**Causes**:
- LM Studio is not running
- No model is loaded in LM Studio
- The port is not 1234

**Solution**: Open LM Studio, load a model, verify the server is listening on port 1234.

---

## 10. Full Reset

### Total reset (delete everything)

```powershell
# 1. Stop services
docker-compose down

# 2. Check volume names
docker volume ls | findstr wordweaveweb

# 3. Delete all volumes
docker volume rm wordweaveweb_postgres_data wordweaveweb_qdrant_data wordweaveweb_document_storage wordweaveweb_redis_data

# 4. Make sure docker/init.sql is up to date (with correct CHECK constraints)

# 5. Full rebuild
docker-compose build --no-cache

# 6. Restart
docker-compose up -d

# 7. Verify
docker-compose ps
```

⚠️ **Embedding models are inside the Docker images (not volumes)** — they survive resets.

### Partial reset (keep accounts, delete project data)

```powershell
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "
DELETE FROM relations;
DELETE FROM chunks;
DELETE FROM documents;
DELETE FROM jobs;
DELETE FROM projects;
"
```

---

## 📊 Pre-deployment Checklist

- [ ] `docker/init.sql`: `jobs_type_check` includes `clustering`, `full_analysis`, `document_analysis`
- [ ] `storage.py`: Embeddings endpoint uses batch ID fetch
- [ ] `clusterer.py`: `n_init=20`, Auto-K debug prints
- [ ] `chat.py`: Timeouts set to 60s minimum
- [ ] `analysis.py`: Stats use real `SELECT COUNT(*)` queries
- [ ] `project.html`: No duplicate `let` declarations, auto-polling enabled
- [ ] `doc_analysis.py`: `_safe_run` wrapper with error catching
- [ ] LM Studio running with a loaded model on port 1234
- [ ] Docker Desktop running and functional

---

## 🗺️ Key File Architecture

```
services/
├── service_a/app/api/
│   └── storage.py          ← Endpoint /embeddings (batch Qdrant)
├── service_b/app/services/
│   └── clusterer.py         ← Auto-K algorithm (KMeans)
│   └── relation_detector.py ← LLM relation detection
├── service_c/app/api/
│   ├── analysis.py          ← Stats endpoint, clustering/relations orchestration
│   ├── chat.py              ← Search, Chat RAG (httpx timeouts)
│   ├── doc_analysis.py      ← Document analysis pipeline
│   └── projects.py          ← Project CRUD
├── service_c/app/templates/
│   └── project.html         ← UI stepper (JavaScript)
docker/
└── init.sql                 ← PostgreSQL schema (CHECK constraints)
```