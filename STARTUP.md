# 🚀 Word Weave Web — Post-Reboot Startup Guide

> Complete procedure to restart the Word Weave Web stack after a PC reboot.

---

## Prerequisites

Before launching anything, make sure these two things are ready:

1. **Docker Desktop** — Launch it and wait for the icon to turn **green** (engine running). No `docker-compose` command will work until Docker is ready.

2. **Local LLM** — Open **LM Studio** (or Ollama) and load a compatible model. The server must listen on **port 1234**. Without this, Chat RAG, relation detection, and document analysis won't work (upload, clustering, and search remain functional).

---

## Step 1 — Launch the stack

Open a PowerShell terminal in the project folder (`WordWeaveWeb/`):

```powershell
docker-compose up -d
```

Docker will start the 6 containers in dependency order:

| Order | Container | Role | Port |
|-------|-----------|------|------|
| 1 | `graphrag-postgres` | PostgreSQL 15 database | 5432 |
| 2 | `graphrag-redis` | Redis 7 cache | 6379 |
| 3 | `graphrag-qdrant` | Qdrant vector storage | 6333 |
| 4 | `graphrag-storage` | Service A — Storage & Embeddings | 8000 |
| 5 | `graphrag-intelligence` | Service B — Chunking, Clustering, Relations | 8001 |
| 6 | `graphrag-orchestrator` | Service C — Web UI & API | 8002 |

⏱️ **Startup time**: approximately 30 to 60 seconds for all services to become `healthy`. Service B is the slowest as it loads the embedding model at startup (~30s).

---

## Step 2 — Verify everything is healthy

```powershell
docker-compose ps
```

All services should show `Up` and `(healthy)`. If a service is `Restarting` or `Exited`, check its logs:

```powershell
docker logs <container-name> --tail 30
```

### Quick endpoint check

```powershell
curl http://localhost:8000/health   # Service A (Storage)
curl http://localhost:8001/health   # Service B (Intelligence)
curl http://localhost:8002/health   # Service C (Orchestrator)
```

Each call should return a JSON with `"status": "healthy"`.

---

## Step 3 — Open the application

In your browser, go to:

```
http://localhost:8002
```

Log in with your account. Your projects, documents, clusters, and relations are **persisted in Docker volumes** — everything is preserved between restarts.

---

## Step 4 — Verify the LLM (optional)

On a project page, the badge at the top indicates **"LLM connected"** (green) or **"LLM disconnected"** (red).

If the LLM is disconnected:

1. Check that LM Studio is running and a model is loaded
2. Check that the server is listening on `http://localhost:1234`
3. Manual test:

```powershell
curl http://localhost:1234/v1/models
```

No need to restart the Docker containers — they reconnect to the LLM automatically.

---

## Summary in 4 commands

```powershell
# 1. Launch Docker Desktop (wait for the green icon)

# 2. Launch LM Studio + load a model on port 1234

# 3. Start the stack
cd <path_to>/WordWeaveWeb
docker-compose up -d

# 4. Verify
docker-compose ps
```

Then open `http://localhost:8002` in your browser.

---

## Troubleshooting

### Ghost container (`Conflict. The container name "..." is already in use`)

After a PC reboot or project folder change, old containers may linger and block startup. To clean them up:

```powershell
# 1. Remove the ghost container
docker rm -f graphrag-qdrant

# 2. Check for other orphan containers
docker ps -a --filter "name=graphrag-"

# 3. If others appear (postgres, redis, etc.), remove them too
docker rm -f graphrag-postgres graphrag-redis graphrag-storage graphrag-intelligence graphrag-orchestrator

# 4. Restart the stack
docker-compose up -d

# 5. Verify
docker-compose ps
```

> 💡 `docker rm -f` removes **containers**, not **volumes**. Your data (projects, documents, embeddings) is preserved.

### Other common issues

| Symptom | Probable cause | Solution |
|---------|---------------|----------|
| `error during connect` | Docker Desktop not running | Open Docker Desktop, wait for the green icon |
| Service in `Restarting` | Dependency not ready | `docker-compose down` then `docker-compose up -d` |
| LLM disconnected | LM Studio not running / model not loaded | Launch LM Studio, load a model |
| Blank page on `:8002` | Service C not ready yet | Wait 30s, refresh the page |
| Data missing | Docker volumes deleted | See `TROUBLESHOOTING.md` section 10 (Reset) |

For deeper diagnostics, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).