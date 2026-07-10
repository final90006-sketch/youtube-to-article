# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_review as BR


def test_extract_cards_prefers_real_brain_quiz_section_after_decoys():
    md = """# 標題
## 補完 profile:working style 測驗徽章
- 這是正文徽章項目，不是卡片
## 三段式總複習
正文說明，不含卡片。
## 🧠 自我檢核
- 問題一？｜答案一
- 問題二？｜答案二
- 問題三？｜答案三
"""
    assert BR.extract_cards_from_md(md) == [
        ("問題一？", "答案一"),
        ("問題二？", "答案二"),
        ("問題三？", "答案三"),
    ]


def test_extract_cards_returns_empty_when_only_decoy_headers_exist():
    md = """# 標題
## 補完 profile:working style 測驗徽章
- 這是正文徽章項目，不是卡片
## 三段式總複習
正文說明，不含卡片。
"""
    assert BR.extract_cards_from_md(md) == []
