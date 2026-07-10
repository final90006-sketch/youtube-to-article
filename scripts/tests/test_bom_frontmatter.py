# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "scripts" / "export_formats.py"


def test_obsidian_export_writes_utf8_sig_bom(tmp_path):
    (tmp_path / "article.md").write_text("# 標題\n\n內容 [0:01]", encoding="utf-8")
    (tmp_path / "transcript.json").write_text(json.dumps({
        "ok": True,
        "meta": {"title": "標題", "webpage_url": "https://www.youtube.com/watch?v=ABCDEFGHIJK"},
        "track": {"source": "manual"},
        "segments": [],
    }, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(EXPORT), str(tmp_path), "--obsidian"],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    assert (tmp_path / "article.obsidian.md").read_bytes()[:3] == b"\xef\xbb\xbf"
