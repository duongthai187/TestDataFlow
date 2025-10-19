import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.support_service.app.storage import LocalAttachmentStorage


@pytest.mark.asyncio
async def test_offload_moves_old_files(tmp_path: Path) -> None:
    storage_dir = tmp_path / "attachments"
    storage_dir.mkdir()
    archive_dir = tmp_path / "archive"

    old_file = storage_dir / "old.txt"
    old_file.write_text("outdated")
    new_file = storage_dir / "new.txt"
    new_file.write_text("fresh")

    old_timestamp = datetime.now(timezone.utc) - timedelta(days=10)
    os.utime(old_file, (old_timestamp.timestamp(), old_timestamp.timestamp()))

    storage = LocalAttachmentStorage(storage_dir)
    moved = await storage.offload_older_than(age=timedelta(days=7), archive_path=archive_dir)

    assert len(moved) == 1
    assert moved[0].exists()
    assert moved[0].read_text() == "outdated"
    assert not old_file.exists()
    assert new_file.exists()

    # Running again should be a no-op and safe to call multiple times.
    moved_again = await storage.offload_older_than(age=timedelta(days=7), archive_path=archive_dir)
    assert moved_again == []

    await storage.close()
