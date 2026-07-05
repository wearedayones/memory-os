import os
import subprocess
from typing import Optional


class GitWrapper:
    def __init__(self, repository_path: str) -> None:
        self.repository_path = os.path.abspath(repository_path)

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git"] + args,
            cwd=self.repository_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def init(self, default_branch: str = "main") -> None:
        if os.path.exists(os.path.join(self.repository_path, ".git")):
            return
        os.makedirs(self.repository_path, exist_ok=True)
        self._run(["init", "-b", default_branch])

    def add(self, paths: list[str]) -> None:
        self._run(["add"] + paths)

    def commit(self, message: str) -> str:
        result = self._run(["commit", "-m", message])
        return result.stdout.strip()

    def log(self, limit: Optional[int] = None) -> list[str]:
        args = ["log", "--oneline", "--all"]
        if limit is not None:
            args += ["-n", str(limit)]
        result = self._run(args, check=False)
        output = result.stdout.strip()
        if not output:
            return []
        return output.splitlines()

    def rollback(self, steps: int = 1) -> str:
        if steps < 1:
            raise ValueError("rollback steps must be >= 1")
        result = self._run(["reset", "--hard", f"HEAD~{steps}"])
        return result.stdout.strip()
