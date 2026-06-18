from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def sha256_file(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_row(values: Iterable[object]) -> str:
    payload = "|".join("" if value is None else str(value).strip() for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
