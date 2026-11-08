import json
import os
from datetime import datetime, timedelta
from pathlib import Path

class CacheManager:
    def __init__(self, cache_dir: str, default_ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_hours = default_ttl_hours

    def _get_cache_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_key}.json"

    def save(self, key: str, data: dict, ttl_hours: int) -> None:
        try:
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(hours=ttl_hours)).isoformat(),
                "data": data
            }

            cache_path = self._get_cache_path(key)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False)
        except (OSError, IOError, ValueError) as e:
            # Fail gracefully — cache is a fallback, don't block pipeline
            print(f"Warning: Failed to cache '{key}': {str(e)}")
            return

    def load(self, key: str, max_age_hours: int | None = None) -> dict | None:
        cache_path = self._get_cache_path(key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

        expires_at = datetime.fromisoformat(cache_data.get("expires_at", ""))
        if datetime.now() > expires_at:
            return None

        if max_age_hours is not None:
            saved_time = datetime.fromisoformat(cache_data["timestamp"])
            if datetime.now() - saved_time > timedelta(hours=max_age_hours):
                return None

        return cache_data["data"]

    def is_expired(self, key: str) -> bool:
        cached = self.load(key)
        return cached is None

    def clear(self, key: str) -> None:
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            cache_path.unlink()
