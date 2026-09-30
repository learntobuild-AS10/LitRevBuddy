from __future__ import annotations

import hashlib
import json


STORY_SCHEMA_VERSION = "paper-story-v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def story_cache_key(*, source_fingerprint: str, provider: str, model: str, mode: str) -> str:
    payload = {
        "source": source_fingerprint,
        "schema": STORY_SCHEMA_VERSION,
        "provider": provider,
        "model": model,
        "mode": mode,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256_text(encoded)
