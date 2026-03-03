# ✦🕸️ Word Weave Web — Reset data (keeps user accounts)
# Usage: .\reset-data.ps1

Write-Host "✦ Reset Word Weave Web..." -ForegroundColor Cyan

# 1. Clear PostgreSQL (keeps owners)
Write-Host "  → PostgreSQL: deleting projects, documents, chunks, relations, jobs..." -ForegroundColor Yellow
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "DELETE FROM relations; DELETE FROM chunks; DELETE FROM documents; DELETE FROM jobs; DELETE FROM projects;"

# 2. Clear Qdrant (delete the volume)
Write-Host "  → Qdrant: deleting volume..." -ForegroundColor Yellow
docker-compose stop service-a
docker volume rm wordweaveweb_qdrant_data 2>$null
Write-Host "  → Qdrant volume deleted" -ForegroundColor Green

# 3. Restart all services
Write-Host "  → Restarting services..." -ForegroundColor Yellow
docker-compose up -d

# 4. Wait for health checks
Write-Host "  → Waiting for health checks..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
docker-compose ps

Write-Host ""
Write-Host "✅ Reset complete! Open http://localhost:8002" -ForegroundColor Green