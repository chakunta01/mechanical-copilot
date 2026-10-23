"""Embedding providers.

Two implementations behind one interface:
- OpenAICompatibleEmbeddings: any /v1/embeddings endpoint (OpenAI, Azure, vLLM, Ollama...).
- HashingEmbeddings: deterministic feature-hashing bag-of-words + bigrams. Zero network,
  zero deps — used for offline dev, CI, and as a graceful fallback.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings
from app.core.errors import UpstreamError

_token_re = re.compile(r"[a-z0-9]+")

# Stopwords excluded from hashing features and lexical scoring: they carry no
# domain meaning and would otherwise create baseline similarity noise between
# any two English texts.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the "
    "this to was were what which with will you your our their per any all can".split()
)


class BaseEmbeddings(ABC):
    name: str = "base"
    dim: int = 256

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class OpenAICompatibleEmbeddings(BaseEmbeddings):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str, dim: int, timeout_s: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.timeout_s = timeout_s

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Embedding request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise UpstreamError(f"Malformed embedding response: {exc}") from exc


class HashingEmbeddings(BaseEmbeddings):
    """Feature hashing on unigrams+bigrams, L2-normalized. Stable, offline, fast."""

    name = "hashing"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> list[str]:
        toks = [t for t in _token_re.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]
        bigrams = [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
        return toks + bigrams

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs: list[list[float]] = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in self._tokens(text):
                # Non-cryptographic feature hashing for the offline embedder, not a security use.
                h = hashlib.md5(tok.encode("utf-8")).digest()  # noqa: S324
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] % 2 == 0 else -1.0
                v[idx] += sign
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vecs.append([x / norm for x in v])
        return vecs


def get_embeddings() -> BaseEmbeddings:
    provider = settings.embeddings_provider
    if provider == "openai_compatible" and settings.embeddings_api_key:
        return OpenAICompatibleEmbeddings(
            base_url=settings.embeddings_base_url,
            api_key=settings.embeddings_api_key,
            model=settings.embeddings_model,
            dim=settings.embeddings_dim,
        )
    # Fallback: offline hashing embeddings (documented behavior, not silent).
    # Uses its own calibrated dim so EMBEDDINGS_DIM (real model) cannot distort it.
    return HashingEmbeddings(dim=settings.hashing_dim)
