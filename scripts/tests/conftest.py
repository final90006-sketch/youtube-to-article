# -*- coding: utf-8 -*-
import re
import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(request):
    """避開本機 AppData Temp ACL 問題；測試暫存只落在 scripts/tests/.tmp。"""
    base = Path(__file__).resolve().parent / ".tmp"
    base.mkdir(exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)[:80]
    p = base / f"{stem}_{uuid.uuid4().hex[:8]}"
    p.mkdir()
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)
        try:
            base.rmdir()
        except OSError:
            pass
