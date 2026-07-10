# -*- coding: utf-8 -*-
import sys
import re
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_review as BR

CARDS = [
    {"id": "a1", "q": "問題一？", "a": "答案一", "cat": "投資理財", "title": "文章甲", "href": "投資理財/甲__x/article.html"},
    {"id": "b2", "q": "問題二？", "a": "答案二", "cat": "科技AI", "title": "文章乙", "href": "科技AI/乙__y/article.html"},
]


def test_build_page_embeds_cards_and_engine():
    html = BR.build_page(CARDS)
    assert '<script id="rv-data"' in html
    m = re.search(r'<script id="rv-data"[^>]*>(.*?)</script>', html, re.S)
    # 內嵌時做了 </ escape，parse 前還原
    raw = m.group(1).replace("<\\/", "</")
    data = json.loads(raw)
    assert len(data) == 2 and data[0]["q"] == "問題一？"
    assert "window.SR" in html and "SR.due" in html            # 引擎＋UI 都在
    assert "每日回顧" in html
    assert "PMingLiU" not in html                              # 字型鐵則
    assert "問題一？" in html and "文章甲" in html              # 內容可見


def test_build_page_empty():
    html = BR.build_page([])
    assert "沒有" in html or "還沒有" in html                  # 空庫友善訊息


def test_cards_json_escaping():
    tricky = [{"id": "z", "q": '含 </script> 與 "引號"？', "a": "a", "cat": "c", "title": "t", "href": "h"}]
    html = BR.build_page(tricky)
    # 內嵌段（id="rv-data" 之後到它自己的 </script>）不得出現字面 </script>
    inner = html.split('id="rv-data"')[1].split("</script>")[0]
    assert "</script>" not in inner
    # 更強：整個內嵌 JSON 段不含任何未轉義的 </（防提早關閉 script）
    assert "</" not in inner
