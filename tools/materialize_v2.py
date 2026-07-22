from __future__ import annotations

import base64
import hashlib
import io
import shutil
import tarfile
from pathlib import Path

ARCHIVE_SHA256 = "9eb72fc152e8a4024119e3a31c6d95dcb0ac4abeb97df72caad9183779a6a336"


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parts_dir = root / ".secploit-bootstrap"
    encoded = "".join(
        path.read_text().strip()
        for path in sorted(parts_dir.glob("part*"))
    )
    payload = base64.b64decode(encoded)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != ARCHIVE_SHA256:
        raise RuntimeError(f"archive checksum mismatch: {actual}")

    for entry in root.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        archive.extractall(root, filter="data")


if __name__ == "__main__":
    main()
