# shared/utils/auto_hop.py
"""
Auto-Hop Graph Traversal — Budget-based best-first exploration.

Instead of a fixed number of hops, the traversal follows the most relevant
path through the knowledge graph as long as the budget allows.

Budget model:
  - Starting budget: 1.0
  - Cost per hop: 1 - cosine_similarity (from the relation)
  - A high-similarity relation (0.95) costs only 0.05 → deep traversal
  - A low-similarity relation (0.30) costs 0.70 → stops early
  - Traversal stops when budget < min cost of any available neighbor

Strategy: Best-first (greedy) — always pick the most similar unvisited neighbor.
Deduplication: visited set ensures each node is explored only once.
Safety: hard max_hops limit prevents runaway traversal.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Set, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from shared.models.orm import Chunk, Relation, Document

logger = logging.getLogger("auto-hop")

# ── Default parameters ──

DEFAULT_BUDGET = 1.0
DEFAULT_MAX_HOPS = 10
DEFAULT_MIN_SIMILARITY = 0.1  # Relations below this are never traversed


@dataclass
class HopResult:
    """A single node discovered during traversal."""
    chunk_id: str
    chromadb_id: Optional[str]
    cluster_id: Optional[int]
    doc_title: str
    hop: int
    budget_remaining: float
    relation_type: str
    relation_similarity: float
    relation_justification: Optional[str]


@dataclass
class AutoHopResult:
    """Complete result of an auto-hop traversal."""
    start_chunk_id: str
    neighbors: List[HopResult] = field(default_factory=list)
    total_hops: int = 0
    budget_used: float = 0.0
    budget_initial: float = DEFAULT_BUDGET
    max_hops: int = DEFAULT_MAX_HOPS
    stopped_reason: str = ""  # "budget_exhausted" | "no_neighbors" | "max_hops_reached"


async def auto_hop_traversal(
    db: AsyncSession,
    start_chunk_id: str,
    project_id: str,
    budget: float = DEFAULT_BUDGET,
    max_hops: int = DEFAULT_MAX_HOPS,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    relation_types: Optional[List[str]] = None,
) -> AutoHopResult:
    """
    Traverse the knowledge graph from a starting chunk using budget-based
    best-first exploration.

    Args:
        db: Database session
        start_chunk_id: UUID of the starting chunk
        project_id: UUID of the project
        budget: Starting budget (default 1.0)
        max_hops: Hard limit on number of hops (default 10)
        min_similarity: Minimum cosine similarity to consider a relation (default 0.1)
        relation_types: Optional filter on relation types

    Returns:
        AutoHopResult with discovered neighbors and traversal metadata
    """
    result = AutoHopResult(
        start_chunk_id=start_chunk_id,
        budget_initial=budget,
        max_hops=max_hops,
    )

    visited: Set[str] = {start_chunk_id}
    remaining_budget = budget
    current_chunk_id = start_chunk_id
    hop_count = 0

    logger.info(
        f"[Auto-Hop] Starting from {start_chunk_id[:8]}... "
        f"budget={budget}, max_hops={max_hops}"
    )

    while hop_count < max_hops and remaining_budget > 0:
        # Fetch all relations for the current chunk
        query = select(Relation).where(
            or_(
                Relation.chunk_a_id == current_chunk_id,
                Relation.chunk_b_id == current_chunk_id,
            ),
            Relation.project_id == project_id,
        )

        if relation_types:
            query = query.where(Relation.type.in_(relation_types))

        rels_result = await db.execute(query)
        relations = rels_result.scalars().all()

        # Build candidate list: (neighbor_id, similarity, relation)
        candidates = []
        for r in relations:
            neighbor_id = str(r.chunk_b_id) if str(r.chunk_a_id) == current_chunk_id else str(r.chunk_a_id)

            if neighbor_id in visited:
                continue

            similarity = r.similarite_cosinus if r.similarite_cosinus is not None else 0.0

            if similarity < min_similarity:
                continue

            cost = 1.0 - similarity
            if cost <= remaining_budget:
                candidates.append((neighbor_id, similarity, cost, r))

        if not candidates:
            result.stopped_reason = "no_neighbors"
            logger.info(
                f"[Auto-Hop] Stopped at hop {hop_count}: no viable neighbors "
                f"(budget={remaining_budget:.3f})"
            )
            break

        # Best-first: pick the candidate with highest similarity (lowest cost)
        candidates.sort(key=lambda c: c[1], reverse=True)
        best_id, best_similarity, best_cost, best_relation = candidates[0]

        # Traverse
        remaining_budget -= best_cost
        hop_count += 1
        visited.add(best_id)
        current_chunk_id = best_id

        # Fetch chunk and document info
        chunk_result = await db.execute(select(Chunk).where(Chunk.id == best_id))
        chunk = chunk_result.scalar_one_or_none()

        doc_title = ""
        if chunk and chunk.document_id:
            doc_result = await db.execute(
                select(Document).where(Document.id == chunk.document_id)
            )
            doc = doc_result.scalar_one_or_none()
            if doc:
                doc_title = doc.title or ""

        hop_result = HopResult(
            chunk_id=best_id,
            chromadb_id=chunk.chromadb_id if chunk else None,
            cluster_id=chunk.cluster_id if chunk else None,
            doc_title=doc_title,
            hop=hop_count,
            budget_remaining=remaining_budget,
            relation_type=best_relation.type,
            relation_similarity=best_similarity,
            relation_justification=best_relation.justification,
        )
        result.neighbors.append(hop_result)

        logger.info(
            f"[Auto-Hop] Hop {hop_count}: → {best_id[:8]}... "
            f"sim={best_similarity:.3f} cost={best_cost:.3f} "
            f"budget_left={remaining_budget:.3f} type={best_relation.type}"
        )

    # Set final state
    result.total_hops = hop_count
    result.budget_used = budget - remaining_budget

    if not result.stopped_reason:
        if hop_count >= max_hops:
            result.stopped_reason = "max_hops_reached"
        elif remaining_budget <= 0:
            result.stopped_reason = "budget_exhausted"

    logger.info(
        f"[Auto-Hop] Done: {hop_count} hops, "
        f"budget {result.budget_used:.3f}/{budget} used, "
        f"reason={result.stopped_reason}"
    )

    return result
