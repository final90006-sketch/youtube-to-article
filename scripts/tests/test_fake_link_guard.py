# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "scripts" / "render_html.py"


def _render(tmp_path, meta):
    md = tmp_path / "article.md"
    js = tmp_path / "transcript.json"
    out = tmp_path / "article.html"
    md.write_text("# 標題\n\n## 章節 [0:01]\n內容", encoding="utf-8")
    js.write_text(json.dumps({"ok": True, "meta": meta, "track": {"source": "md"}, "segments": []},
                             ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(RENDER), "--md", str(md), "--json", str(js), "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return out.read_text(encoding="utf-8")


def test_document_without_webpage_url_does_not_synthesize_youtube_link(tmp_path):
    html = _render(tmp_path, {"type": "document", "id": "ABCDEFGHIJK", "title": "文件"})
    assert "youtu.be" not in html
    assert "watch?v=" not in html


def test_av_with_youtube_id_can_synthesize_link(tmp_path):
    html = _render(tmp_path, {"id": "ABCDEFGHIJK", "title": "影片"})
    assert "https://youtu.be/ABCDEFGHIJK" in html
