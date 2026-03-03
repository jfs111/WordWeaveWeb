# services/service_c/app/api/projects.py
"""Projects API — CRUD, stats, quotas"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging

from shared.config.database import get_db
from shared.models.orm import Owner, Project, Document, ProjectMember
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("service-c.projects")

# Plan quotas
PLAN_QUOTAS = {
    "free":       {"max_projects": 3,   "max_documents": 100,  "max_storage_mb": 500},
    "pro":        {"max_projects": 20,  "max_documents": 5000, "max_storage_mb": 50000},
    "enterprise": {"max_projects": 999, "max_documents": 99999, "max_storage_mb": 999999},
}


# ── Models ──

class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: Optional[str] = None
    chunking_size: int = Field(default=1500, ge=100, le=5000)
    chunking_overlap: int = Field(default=200, ge=0, le=1000)
    similarity_threshold: float = Field(default=0.6, ge=0.1, le=0.99)

class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    chunking_size: Optional[int] = None
    chunking_overlap: Optional[int] = None
    similarity_threshold: Optional[float] = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    total_documents: int
    total_chunks: int
    total_relations: int
    chunking_size: int
    chunking_overlap: int
    similarity_threshold: float
    created_at: str


# ── Endpoints ──

@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all projects for current user"""
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == current_user.id, Project.status != "deleted")
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "total_documents": p.total_documents,
            "total_chunks": p.total_chunks,
            "total_relations": p.total_relations,
            "chunking_size": p.chunking_size,
            "chunking_overlap": p.chunking_overlap,
            "similarity_threshold": p.similarity_threshold,
            "created_at": p.created_at.isoformat(),
        }
        for p in projects
    ]


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: CreateProjectRequest,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new project"""
    # Check quota
    quotas = PLAN_QUOTAS.get(current_user.plan, PLAN_QUOTAS["free"])
    result = await db.execute(
        select(func.count(Project.id))
        .where(Project.owner_id == current_user.id, Project.status != "deleted")
    )
    current_count = result.scalar()
    if current_count >= quotas["max_projects"]:
        raise HTTPException(
            status_code=403,
            detail=f"Project limit reached ({quotas['max_projects']} for {current_user.plan} plan)"
        )

    # Check unique name
    existing = await db.execute(
        select(Project).where(Project.owner_id == current_user.id, Project.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Project name already exists")

    project = Project(
        owner_id=current_user.id,
        name=request.name,
        description=request.description,
        chunking_size=request.chunking_size,
        chunking_overlap=request.chunking_overlap,
        similarity_threshold=request.similarity_threshold,
        max_documents=quotas["max_documents"],
        max_storage_mb=quotas["max_storage_mb"],
        chromadb_path=f"{current_user.id}/{{}}"  # Will be set after creation
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    # Set chromadb_path with actual project ID
    project.chromadb_path = f"{current_user.id}/{project.id}"
    await db.commit()

    # Add owner as project member
    member = ProjectMember(project_id=project.id, owner_id=current_user.id, role="owner")
    db.add(member)
    await db.commit()

    logger.info(f"Project created: {project.name} by {current_user.email}")

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "total_documents": 0,
        "total_chunks": 0,
        "total_relations": 0,
        "chunking_size": project.chunking_size,
        "chunking_overlap": project.chunking_overlap,
        "similarity_threshold": project.similarity_threshold,
        "created_at": project.created_at.isoformat(),
    }


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific project"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "total_documents": project.total_documents,
        "total_chunks": project.total_chunks,
        "total_relations": project.total_relations,
        "chunking_size": project.chunking_size,
        "chunking_overlap": project.chunking_overlap,
        "similarity_threshold": project.similarity_threshold,
        "created_at": project.created_at.isoformat(),
    }


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: UpdateProjectRequest,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update project settings"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if request.name is not None:
        project.name = request.name
    if request.description is not None:
        project.description = request.description
    if request.chunking_size is not None:
        project.chunking_size = request.chunking_size
    if request.chunking_overlap is not None:
        project.chunking_overlap = request.chunking_overlap
    if request.similarity_threshold is not None:
        project.similarity_threshold = request.similarity_threshold

    await db.commit()
    await db.refresh(project)

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "total_documents": project.total_documents,
        "total_chunks": project.total_chunks,
        "total_relations": project.total_relations,
        "chunking_size": project.chunking_size,
        "chunking_overlap": project.chunking_overlap,
        "similarity_threshold": project.similarity_threshold,
        "created_at": project.created_at.isoformat(),
    }


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Soft-delete a project"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = "deleted"
    await db.commit()

    # TODO: Also call Service A to delete ChromaDB data

    return {"status": "deleted", "project_id": project_id}
