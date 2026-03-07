# services/service_b/app/services/relation_detector.py
"""Relation detection service — LLM-based analysis within clusters.
Adapted from POC: rncp_detect_relations.py"""

import os
import json
import numpy as np
from typing import List, Dict, Optional, Any
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI
import logging
import time

logger = logging.getLogger("service-b.relation-detector")

LLM_URL = os.getenv("LLM_URL", "http://host.docker.internal:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")


class RelationDetector:
    """
    Detects semantic relations between chunks using LLM.
    Adapted from POC: RNCPRelationDetector

    Pipeline per cluster:
      1. Get all chunks + embeddings in cluster
      2. Pre-filter pairs by cosine similarity >= threshold
      3. Send filtered pairs to LLM for analysis
      4. Parse JSON response, return validated relations
    """

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
        similarity_threshold: float = 0.6,
        max_pairs_per_cluster: int = 500,
    ):
        self.llm_url = llm_url or LLM_URL
        self.llm_model = llm_model or LLM_MODEL
        self.similarity_threshold = similarity_threshold
        self.max_pairs_per_cluster = max_pairs_per_cluster
        self.client = None
        self.stats = {
            "total_pairs_analyzed": 0,
            "total_relations_found": 0,
            "llm_calls": 0,
            "filtered_by_cosine": 0,
            "errors": 0,
        }

    def _get_client(self) -> OpenAI:
        """Lazy-init LLM client with timeout"""
        if self.client is None:
            self.client = OpenAI(
                base_url=self.llm_url,
                api_key="lm-studio",
                timeout=120,
            )
        return self.client

    def test_connection(self) -> bool:
        """Test LLM connection"""
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": "Test"}],
                max_tokens=10,
            )
            logger.info(f"LLM connection OK: {self.llm_url} / {self.llm_model}")
            return True
        except Exception as e:
            logger.error(f"LLM connection failed: {e}")
            return False

    def detect_relations_for_cluster(
        self,
        cluster_id: int,
        chunk_ids: List[str],
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
    ) -> List[Dict]:
        """
        Detect relations within a single cluster.

        Args:
            cluster_id: Cluster identifier
            chunk_ids: List of chunk IDs in this cluster
            texts: List of chunk texts
            embeddings: List of embedding vectors
            metadatas: List of chunk metadata dicts

        Returns:
            List of relation dicts
        """
        n = len(chunk_ids)
        if n < 2:
            logger.info(f"Cluster {cluster_id}: {n} chunk(s), skipping")
            return []

        logger.info(f"Cluster {cluster_id}: {n} chunks, analyzing...")

        # Build all pairs
        emb_array = np.array(embeddings)
        pairs = []

        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((i, j))

        total_pairs = len(pairs)

        # Limit pairs
        if total_pairs > self.max_pairs_per_cluster:
            logger.warning(f"Cluster {cluster_id}: limiting from {total_pairs} to {self.max_pairs_per_cluster} pairs")
            pairs = pairs[:self.max_pairs_per_cluster]

        # Pre-filter by cosine similarity
        filtered_pairs = []
        for i, j in pairs:
            sim = cosine_similarity(
                emb_array[i].reshape(1, -1),
                emb_array[j].reshape(1, -1)
            )[0][0]

            if sim >= self.similarity_threshold:
                filtered_pairs.append((i, j, float(sim)))

        self.stats["filtered_by_cosine"] += (len(pairs) - len(filtered_pairs))

        logger.info(
            f"Cluster {cluster_id}: {len(filtered_pairs)}/{total_pairs} pairs "
            f"after cosine filter (threshold={self.similarity_threshold})"
        )

        if not filtered_pairs:
            return []

        # Analyze pairs with LLM
        relations = []
        for idx_a, idx_b, similarity in filtered_pairs:
            self.stats["total_pairs_analyzed"] += 1

            result = self._analyze_pair(
                chunk_a_id=chunk_ids[idx_a],
                text_a=texts[idx_a],
                meta_a=metadatas[idx_a],
                chunk_b_id=chunk_ids[idx_b],
                text_b=texts[idx_b],
                meta_b=metadatas[idx_b],
            )

            if result and result.get("existe", False):
                rel_type = result.get("type", "AUTRE")
                # Validate type
                valid_types = {
                    "PREREQUIS", "COMPLEMENTAIRE", "SIMILAIRE", "METHODOLOGIQUE",
                    "APPLICATION", "EXEMPLE", "SUITE_LOGIQUE", "TRANSVERSAL", "AUTRE"
                }
                if rel_type not in valid_types:
                    rel_type = "AUTRE"

                intensite = result.get("intensite", "MOYENNE")
                if intensite not in {"FAIBLE", "MOYENNE", "FORTE"}:
                    intensite = "MOYENNE"

                relation = {
                    "chunk_a_id": chunk_ids[idx_a],
                    "chunk_b_id": chunk_ids[idx_b],
                    "type": rel_type,
                    "intensite": intensite,
                    "confiance": min(1.0, max(0.0, float(result.get("confiance", 0.5)))),
                    "similarite_cosinus": similarity,
                    "justification": str(result.get("justification", ""))[:500],
                }
                relations.append(relation)
                self.stats["total_relations_found"] += 1

            # Small pause to avoid overwhelming LM Studio
            time.sleep(0.05)

        logger.info(f"Cluster {cluster_id}: {len(relations)} relations found")
        return relations

    def _analyze_pair(
        self,
        chunk_a_id: str,
        text_a: str,
        meta_a: Dict,
        chunk_b_id: str,
        text_b: str,
        meta_b: Dict,
        max_retries: int = 2,
    ) -> Optional[Dict]:
        """Analyze a single pair of chunks with LLM, with retry on failure"""
        for attempt in range(max_retries):
            try:
                prompt = self._build_prompt(text_a, meta_a, text_b, meta_b)

                client = self._get_client()
                response = client.chat.completions.create(
                    model=self.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=300,
                )

                self.stats["llm_calls"] += 1

                response_text = response.choices[0].message.content.strip()

                # Clean markdown fences if present
                if response_text.startswith("```"):
                    parts = response_text.split("```")
                    if len(parts) >= 2:
                        response_text = parts[1]
                        if response_text.startswith("json"):
                            response_text = response_text[4:]

                # Try to extract JSON from response
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    response_text = response_text[json_start:json_end]

                result = json.loads(response_text)
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error for pair {chunk_a_id}/{chunk_b_id}: {e}")
                self.stats["errors"] += 1
                return None
            except Exception as e:
                logger.warning(f"LLM error (attempt {attempt+1}/{max_retries}) for pair {chunk_a_id}/{chunk_b_id}: {e}")
                self.stats["errors"] += 1
                if attempt < max_retries - 1:
                    time.sleep(2)
                    self.client = None  # Force reconnect
                    continue
                return None

    def _build_prompt(
        self,
        text_a: str,
        meta_a: Dict,
        text_b: str,
        meta_b: Dict,
    ) -> str:
        """Build analysis prompt — adapted from POC"""
        title_a = meta_a.get("title", "Document A")
        title_b = meta_b.get("title", "Document B")
        cat_a = meta_a.get("category", "N/A")
        cat_b = meta_b.get("category", "N/A")

        # Truncate texts to avoid exceeding context window
        max_text = 1500
        text_a_trunc = text_a[:max_text] if len(text_a) > max_text else text_a
        text_b_trunc = text_b[:max_text] if len(text_b) > max_text else text_b

        prompt = f"""Tu es un expert en analyse de relations entre contenus de formation professionnelle.

DOCUMENT A : "{title_a}" (Module : {cat_a})
[CONTENU] {text_a_trunc}

DOCUMENT B : "{title_b}" (Module : {cat_b})
[CONTENU] {text_b_trunc}

TÂCHES :
1. Y a-t-il une relation pédagogique ou thématique significative entre ces deux contenus ? (OUI/NON)

2. Si OUI, quel est le TYPE de relation ?
   - PREREQUIS : A est un prérequis pour B (ou inversement)
   - COMPLEMENTAIRE : A complète B, ils se renforcent mutuellement
   - SIMILAIRE : Même concept, reformulation ou exemple similaire
   - METHODOLOGIQUE : Même approche/méthode appliquée
   - APPLICATION : A est la théorie, B est l'application pratique (ou inversement)
   - EXEMPLE : A illustre un concept de B (ou inversement)
   - SUITE_LOGIQUE : B est la suite naturelle de A dans un parcours d'apprentissage
   - TRANSVERSAL : Concept qui traverse plusieurs modules
   - AUTRE : (préciser)

3. Quelle est l'INTENSITÉ de la relation ? (FAIBLE / MOYENNE / FORTE)

4. JUSTIFICATION : Explique en 1-2 phrases courtes pourquoi cette relation existe.

RÉPONDS UNIQUEMENT EN JSON (sans markdown, sans backticks) :
{{
  "existe": true ou false,
  "type": "PREREQUIS" ou autre,
  "intensite": "FAIBLE" ou "MOYENNE" ou "FORTE",
  "justification": "...",
  "confiance": 0.8
}}"""

        return prompt

    def get_stats(self) -> Dict:
        """Return current statistics"""
        return dict(self.stats)

    def reset_stats(self):
        """Reset statistics"""
        self.stats = {
            "total_pairs_analyzed": 0,
            "total_relations_found": 0,
            "llm_calls": 0,
            "filtered_by_cosine": 0,
            "errors": 0,
        }