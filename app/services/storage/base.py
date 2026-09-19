from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Union


class BaseStorageService(ABC):
    """Abstract interface for file storage.
    
    Designed to allow transparent swapping between Local Filesystem,
    AWS S3, or any object storage provider without touching application code.
    """

    @abstractmethod
    def save(self, content: Union[BinaryIO, bytes], filename: str) -> str:
        """Save file content and return the stored identifier/relative path."""
        pass

    @abstractmethod
    def get_path(self, filename: str) -> Path:
        """Get absolute Path to the stored file on local storage."""
        pass

    @abstractmethod
    def read(self, filename: str) -> bytes:
        """Read full content of the file."""
        pass

    @abstractmethod
    def delete(self, filename: str) -> bool:
        """Delete stored file. Return True if deleted, False if not found."""
        pass

    @abstractmethod
    def exists(self, filename: str) -> bool:
        """Check if file exists in storage."""
        pass
