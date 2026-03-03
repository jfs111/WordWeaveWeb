# services/service_b/app/services/clusterer.py
"""Clustering service with auto-K — adapted from POC run_rncp_pipeline.py"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, davies_bouldin_score
import logging

logger = logging.getLogger("service-b.clusterer")


class ClusteringService:
    """
    K-means clustering with automatic K detection.
    Adapted from POC: RNCPPipeline.find_optimal_k() + cluster_documents()
    
    Auto-K algorithm:
      - Test K range: √(N/2) to 2×√N (step 2)
      - Score each K with: elbow (inertia), silhouette, Davies-Bouldin
      - Combine scores: elbow_k * 0.3 + silhouette_k * 0.4 + davies_k * 0.3
      - Select K closest to weighted average
    """

    def cluster(
        self,
        embeddings: List[List[float]],
        method: str = "auto-k",
        force_k: Optional[int] = None,
        k_range: Optional[Tuple[int, int]] = None,
    ) -> Dict:
        """Run clustering on embeddings"""
        X = np.array(embeddings)
        n_samples = len(X)
        print(f"[Clustering] Received {n_samples} samples, method={method}, force_k={force_k}", flush=True)

        if n_samples < 3:
            return {
                "labels": [0] * n_samples,
                "n_clusters": 1,
                "silhouette_score": 0.0,
                "davies_bouldin_score": 0.0,
            }

        if force_k:
            k = min(force_k, n_samples - 1)
        elif method == "auto-k":
            k = self._find_optimal_k(X, k_range)
        else:
            k = max(2, int(np.sqrt(n_samples)))

        # Run final K-means
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=20, max_iter=300)
        labels = kmeans.fit_predict(X)

        sil = float(silhouette_score(X, labels)) if k > 1 else 0.0
        db = float(davies_bouldin_score(X, labels)) if k > 1 else 0.0

        logger.info(f"Clustering: {n_samples} samples → K={k}, silhouette={sil:.3f}, DB={db:.3f}")

        return {
            "labels": labels.tolist(),
            "n_clusters": int(k),
            "silhouette_score": sil,
            "davies_bouldin_score": db,
        }

    def _find_optimal_k(self, X: np.ndarray, k_range: Optional[Tuple[int, int]] = None) -> int:
        """Find optimal K using elbow + silhouette + Davies-Bouldin"""
        n = len(X)

        if k_range:
            min_k, max_k = k_range
        else:
            min_k = max(2, int(np.sqrt(n / 2)))
            max_k = min(50, int(np.sqrt(n) * 2))

        if min_k >= max_k:
            max_k = min_k + 4

        k_values = list(range(min_k, max_k + 1, 2))
        print(f"[Auto-K] n={n}, testing K range: {k_values}", flush=True)
        if not k_values:
            return max(2, min_k)

        inertias = []
        sil_scores = []
        db_scores = []

        for k in k_values:
            if k >= n:
                continue
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=20)
            labels = kmeans.fit_predict(X)
            sil = silhouette_score(X, labels)
            db = davies_bouldin_score(X, labels)
            inertias.append(kmeans.inertia_)
            sil_scores.append(sil)
            db_scores.append(db)
            print(f"[Auto-K] K={k}: silhouette={sil:.4f}, DB={db:.4f}, inertia={kmeans.inertia_:.1f}", flush=True)

        valid_k = k_values[:len(inertias)]

        if len(valid_k) < 2:
            return valid_k[0] if valid_k else 2

        # Elbow: max second derivative
        inertias_norm = np.array(inertias)
        inertias_norm = (inertias_norm - inertias_norm.min()) / (inertias_norm.max() - inertias_norm.min() + 1e-10)
        diffs = np.diff(inertias_norm)
        second_diffs = np.diff(diffs)
        elbow_idx = int(np.argmax(second_diffs)) + 1 if len(second_diffs) > 0 else 0
        k_elbow = valid_k[min(elbow_idx, len(valid_k) - 1)]

        # Best silhouette
        k_silhouette = valid_k[int(np.argmax(sil_scores))]

        # Best Davies-Bouldin (lowest)
        k_db = valid_k[int(np.argmin(db_scores))]

        # Weighted combination
        k_optimal_float = k_elbow * 0.3 + k_silhouette * 0.4 + k_db * 0.3
        k_optimal = valid_k[int(np.argmin([abs(k - k_optimal_float) for k in valid_k]))]

        print(f"[Auto-K] RESULT: elbow={k_elbow}, silhouette={k_silhouette}, DB={k_db} → optimal={k_optimal}", flush=True)
        return k_optimal