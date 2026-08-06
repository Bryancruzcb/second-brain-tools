"""Deterministic test doubles. No model downloads in CI."""
import hashlib

import numpy as np

DIM = 64


class BagOfWordsEmbedder:
    """Stand-in for SentenceTransformer: hashed, normalized bag-of-words.

    Texts sharing words get similar vectors, so ranking behaves sensibly
    and the e2e test can genuinely fail if retrieval wiring breaks.
    """

    def encode(self, texts):
        out = []
        for text in texts:
            vec = np.zeros(DIM, dtype=np.float32)
            for word in text.lower().split():
                h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
                vec[h % DIM] += 1.0
            norm = np.linalg.norm(vec)
            out.append(vec / norm if norm > 0 else vec)
        return np.array(out)
