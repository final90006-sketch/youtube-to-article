# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "scripts" / "render_html.py"
sys.path.insert(0, str(ROOT / "scripts"))
import render_html as R


def test_document_webpage_url_is_escaped_in_html_attrs(tmp_path):
    bad = '"><img src=x onerror=alert(1)>'
    md = tmp_path / "article.md"
    js = tmp_path / "transcript.json"
    out = tmp_path / "article.html"
    md.write_text("# 標題\n\n## 章節 [0:01]\n內容", encoding="utf-8")
    js.write_text(json.dumps({"ok": True, "meta": {"type": "document", "title": "文件", "webpage_url": bad},
                              "track": {"source": "web"}, "segments": []}, ensure_ascii=False),
                  encoding="utf-8")
    p = subprocess.run([sys.executable, str(RENDER), "--md", str(md), "--json", str(js), "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    html = out.read_text(encoding="utf-8")
    assert '"><img' not in html
    assert "&quot;" in html and "&gt;" in html


def test_clean_youtube_timecode_href_is_unchanged():
    url = "https://www.youtube.com/watch?v=ABCDEFGHIJK"
    rendered = R.make_inline(url)("[0:01]")
    assert f'href="{url}&t=1s"' in rendered
