# -*- coding: utf-8 -*-
"""Task4 整合測試：index 首頁含「每日回顧」入口鈕。

（計畫 Task4 Step1 的 test_av_index_button_only_addition() 是空測試，
 已依 pre-flight 裁決刪除；av 零回歸改由控制者級「既有卡片區塊位元組級比對」覆蓋。）
"""
import sys
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]   # scripts/
sys.path.insert(0, str(SCRIPTS))


def test_build_index_has_review_button(tmp_path):
    # 造最小 BASE：一個分類夾一篇（有 transcript.json + article.html）
    d = tmp_path / "測試分類" / "篇一__id1"
    d.mkdir(parents=True)
    (d / "transcript.json").write_text(
        '{"meta":{"title":"篇一","type":"av"},"track":{},"segments":[]}', encoding="utf-8")
    (d / "article.md").write_text("# 篇一\n## 🧠 自我檢核\n- Q？｜A", encoding="utf-8")
    (d / "article.html").write_text("<html></html>", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(SCRIPTS / "build_index.py"), "--base", str(tmp_path)],
        check=True)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'review.html' in html and '每日回顧' in html   # 入口鈕存在
