import json
import os
import tempfile
from typing import Any


class JsonStore:
    def __init__(self, directory: str) -> None:
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)

    def _resolve_path(self, key: str) -> str:
        safe_key = key.replace("..", "_").replace("/", "_").replace("\\", "_")
        return os.path.join(self.directory, f"{safe_key}.json")

    def read(self, key: str) -> dict[str, Any] | None:
        path = self._resolve_path(key)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def write(self, key: str, data: dict[str, Any]) -> None:
        path = self._resolve_path(key)
        dir_name = os.path.dirname(path)
        os.makedirs(dir_name, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def delete(self, key: str) -> None:
        path = self._resolve_path(key)
        if os.path.exists(path):
            os.remove(path)

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        for filename in os.listdir(self.directory):
            if filename.endswith(".json"):
                keys.append(filename[:-5])
        return sorted(keys)

    def read_all(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key in self.list_keys():
            data = self.read(key)
            if data is not None:
                result[key] = data
        return result
