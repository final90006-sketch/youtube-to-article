# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
import build_review as BR

MD = """# 標題
## 💡 重點洞察
- 洞察一
## 🧠 自我檢核
- 為什麼風報比比勝率重要？｜因為勝率有天花板、風報比可拉很多倍。
- 什麼是大部位損益、小部位試單？　｜　沒把握用最小單位換感覺，對了再加碼。
## ❝ 金句
> 「一句話」
"""


def test_extract_cards_basic():
    cards = BR.extract_cards_from_md(MD)
    assert len(cards) == 2
    assert cards[0][0] == "為什麼風報比比勝率重要？"
    assert cards[0][1].startswith("因為勝率有天花板")
    # 全形｜前後空白要 strip
    assert cards[1][0] == "什麼是大部位損益、小部位試單？"
    assert cards[1][1] == "沒把握用最小單位換感覺，對了再加碼。"


def test_extract_cards_no_quiz_section():
    assert BR.extract_cards_from_md("# 只有標題\n## 💡 重點洞察\n- x") == []


def test_extract_stops_at_next_h2():
    md = "## 🧠 自我檢核\n- Q1？｜A1\n## 下一節\n- 這行不是卡"
    cards = BR.extract_cards_from_md(md)
    assert cards == [("Q1？", "A1")]


def test_card_id_stable_and_normalized():
    # 同 href 同問題（僅空白差異）→ 同 id
    a = BR.card_id("cat/x/article.html", "為什麼 A？")
    b = BR.card_id("cat/x/article.html", "為什麼A？ ")
    assert a == b
    # 不同 href → 不同 id
    assert a != BR.card_id("cat/y/article.html", "為什麼 A？")
    assert len(a) == 12
