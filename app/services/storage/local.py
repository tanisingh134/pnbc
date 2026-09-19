import os
from pathlib import Path
from typing import BinaryIO, Union
from app.core.exceptions import BadRequestException
from app.services.storage.base import BaseStorageService


class LocalStorageService(BaseStorageService):
    """Local filesystem implementation of BaseStorageService with path traversal guards."""

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, filename: str) -> Path:
        """Sanitize filename and ensure path is strictly within base_dir."""
        # Strip path navigation
        clean_name = Path(filename).name
        if not clean_name or clean_name in (".", ".."):
            raise BadRequestException("Invalid filename provided")

        resolved_path = (self.base_dir / clean_name).resolve()

        # Strict containment check
        try:
            resolved_path.relative_to(self.base_dir)
        except ValueError:
            raise BadRequestException("Directory traversal detected in storage path")

        return resolved_path

    def save(self, content: Union[BinaryIO, bytes], filename: str) -> str:
        """Save file content to disk safely."""
        target_path = self._resolve_safe_path(filename)

        if isinstance(content, bytes):
            with open(target_path, "wb") as f:
                f.write(content)
        else:
            with open(target_path, "wb") as f:
                # Stream in 64KB chunks to prevent high memory consumption
                while chunk := content.read(65536):
                    f.write(chunk)

        return target_path.name

    def get_path(self, filename: str) -> Path:
        """Get absolute path to stored file."""
        return self._resolve_safe_path(filename)

    def read(self, filename: str) -> bytes:
        """Read content of stored file."""
        target_path = self._resolve_safe_path(filename)
        if not target_path.is_file():
            raise FileNotFoundError(f"File {filename} not found in storage")
        with open(target_path, "rb") as f:
            return f.read()

    def delete(self, filename: str) -> bool:
        """Delete stored file."""
        try:
            target_path = self._resolve_safe_path(filename)
            if target_path.is_file():
                target_path.unlink()
                return True
            return False
        except Exception:
            return False

    def exists(self, filename: str) -> bool:
        """Check if file exists."""
        try:
            target_path = self._resolve_safe_path(filename)
            return target_path.is_file()
        except Exception:
            return False
