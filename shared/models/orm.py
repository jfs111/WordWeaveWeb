# shared/models/orm.py
"""SQLAlchemy ORM models — mirrors docker/init.sql"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    UniqueConstraint, CheckConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from shared.config.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Owner(Base):
    __tablename__ = "owners"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    type = Column(String(20), default="individual")
    plan = Column(String(20), default="free")
    api_key = Column(String(64), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Processing config
    chunking_size = Column(Integer, default=1500)
    chunking_overlap = Column(Integer, default=200)
    embedding_model = Column(String(100), default="paraphrase-multilingual-MiniLM-L12-v2")
    clustering_method = Column(String(50), default="auto-k")
    similarity_threshold = Column(Float, default=0.6)

    # Quotas
    max_documents = Column(Integer, default=100)
    max_storage_mb = Column(Integer, default=500)

    # Stats
    total_documents = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)
    total_relations = Column(Integer, default=0)
    total_storage_mb = Column(Float, default=0)

    chromadb_path = Column(String(500))
    status = Column(String(20), default="active")

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner = relationship("Owner", back_populates="projects")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("owner_id", "name"),)


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    filename = Column(String(500), nullable=False)
    title = Column(String(500))
    category = Column(String(255))
    subcategory = Column(String(255))

    file_path = Column(String(1000))
    file_size_mb = Column(Float, default=0)
    pages = Column(Integer, default=0)

    status = Column(String(20), default="uploaded")
    error_message = Column(Text)
    processed_at = Column(DateTime(timezone=True))

    total_chunks = Column(Integer, default=0)
    total_relations = Column(Integer, default=0)

    metadata_ = Column("metadata", JSONB, default={})

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    chromadb_id = Column(String(255), unique=True)

    text_preview = Column(String(500))
    word_count = Column(Integer, default=0)

    page_start = Column(Integer)
    page_end = Column(Integer)
    char_start = Column(Integer)
    char_end = Column(Integer)

    cluster_id = Column(Integer)
    has_relations = Column(Boolean, default=False)
    relation_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    document = relationship("Document", back_populates="chunks")


class Relation(Base):
    __tablename__ = "relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    chunk_a_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    chunk_b_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)

    type = Column(String(50), nullable=False)
    intensite = Column(String(20), default="MOYENNE")
    confiance = Column(Float, default=0.5)
    similarite_cosinus = Column(Float)

    justification = Column(Text)
    metadata_ = Column("metadata", JSONB, default={})

    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "chunk_a_id", "chunk_b_id"),)


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "owner_id"),)

    project = relationship("Project", back_populates="members")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), nullable=False)

    type = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")

    progress = Column(Float, default=0)
    current_step = Column(String(255))

    input_data = Column(JSONB, default={})
    output_data = Column(JSONB, default={})
    error_message = Column(Text)

    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)
