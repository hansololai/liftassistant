"""Content-Addressable Storage (CAS) for receipts and documents.
Enforces Decision 18:
1. Immutable SHA-256 hash addressing.
2. Structured directory partitioning: data/receipt_store/YYYY-MM/{hash}.{ext}.
3. Zero-cost duplicate detection.
"""

from datetime import datetime
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CAS_ROOT = Path(os.environ.get("LIFTASSISTANT_CAS_ROOT", Path("data") / "receipt_store"))


class CASStorage:
    """Content-Addressable Storage engine for raw receipt photos and documents."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or DEFAULT_CAS_ROOT
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_sha256(content: bytes) -> str:
        """Calculate SHA-256 hexadecimal digest of raw bytes."""
        hasher = hashlib.sha256()
        hasher.update(content)
        return hasher.hexdigest()

    def store_file(
        self,
        content: bytes,
        original_filename: str,
        mime_type: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Store bytes into CAS partition YYYY-MM/{sha256}.{ext}.

        Detects duplicates: if the identical hash is already saved, returns
        the existing path with is_duplicate = True without redundant disk writes.
        """
        file_hash = self.compute_sha256(content)
        ext = Path(original_filename).suffix.lower() or ".jpg"

        # Partition by Year-Month
        ts = timestamp or datetime.now()
        partition = ts.strftime("%Y-%m")
        partition_dir = self.root_dir / partition
        partition_dir.mkdir(parents=True, exist_ok=True)

        target_path = partition_dir / f"{file_hash}{ext}"
        is_duplicate = target_path.exists()

        if not is_duplicate:
            target_path.write_bytes(content)
            logger.info("CAS: Stored new document %s -> %s", original_filename, target_path)
        else:
            logger.info("CAS: Duplicate detected for hash %s, skipping write.", file_hash)

        return {
            "file_hash": file_hash,
            "file_path": str(target_path).replace("\\", "/"),
            "file_size_bytes": len(content),
            "original_filename": original_filename,
            "mime_type": mime_type or "image/jpeg",
            "is_duplicate": is_duplicate,
            "created_at": ts.isoformat(),
        }

    def get_file_path(self, file_hash: str) -> Optional[Path]:
        """Search CAS partitions for a file matching the given SHA-256 hash."""
        # Check all monthly subdirectories
        for path in self.root_dir.glob(f"*/*{file_hash}*"):
            if path.is_file():
                return path
        return None

    def read_file(self, file_hash: str) -> Optional[bytes]:
        """Read bytes of file by hash."""
        path = self.get_file_path(file_hash)
        if path and path.exists():
            return path.read_bytes()
        return None

    def verify_integrity(self, file_path: Path, expected_hash: str) -> bool:
        """Verify file bytes match the expected SHA-256 hash."""
        if not file_path.exists():
            return False
        content = file_path.read_bytes()
        return self.compute_sha256(content).lower() == expected_hash.lower()
