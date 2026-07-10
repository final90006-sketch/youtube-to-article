# scripts/tests/test_cite_render.py
# Task 2（多來源綜合·渲染端）：citation 錨點＋來源附錄
# 6 案：_circled_to_int／cite 錨點／av 短路／多 cite／render_sources 空／html.escape
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import render_html as R


def test_circled_to_int():
    assert R._circled_to_int("③") == 3
    assert R._circled_to_int("⑳") == 20
    assert R._circled_to_int("21") == 21          # 超 20 純數字 fallback


def test_cite_becomes_anchor_when_in_src_ids():
    inline = R.make_inline("", src_ids={1, 3})
    out = inline("這個論點很重要（來源③）")
    assert '<a class="cite" href="#src-3">（來源③）</a>' in out


def test_cite_plain_when_not_in_src_ids_or_av():
    # av / 單源：src_ids 空 → 不套正則、原樣純文字
    inline_av = R.make_inline("")
    assert "href=\"#src-3\"" not in inline_av("（來源③）")
    assert "（來源③）" in inline_av("（來源③）")
    # N 不在 src_ids（如只有 2 源卻標了來源5）→ 原樣，不生死錨點
    inline2 = R.make_inline("", src_ids={1, 2})
    assert "href=\"#src-5\"" not in inline2("（來源⑤）")


def test_multi_cite_in_one_paragraph():
    inline = R.make_inline("", src_ids={1, 3})
    out = inline("綜合兩源（來源①）（來源③）")
    assert out.count('class="cite"') == 2


def test_render_sources_empty():
    assert R.render_sources([]) == ""


def test_render_sources_nonempty_and_escape():
    html = R.render_sources([{"n":1,"mark":"①","title":"甲","source":"md","url":"","display":"甲","text":"甲全文\n第二段"}])
    assert 'id="src-1"' in html and "甲全文" in html and "<details" in html
    # html.escape：原文含 < 不破版
    h2 = R.render_sources([{"n":1,"mark":"①","title":"x","source":"md","url":"","display":"x","text":"a<b>c"}])
    assert "a&lt;b&gt;c" in h2


def test_mixed_token_no_crash_renders_plain():
    # Minor 修：舊正則 [①-⑳0-9]+ 會吃混合 token「①2」→ _circled_to_int 走 int("①2") 拋 ValueError → 整頁 render 崩潰。
    # 修後：收斂成「單一圈號｜純數字串」，混合 token 不匹配→原樣純文字降級（無 href、無例外）。
    inline = R.make_inline("", src_ids={1, 2})
    out = inline("這句混了圈號與數字（來源①2）結尾")   # 不得拋例外
    assert 'class="cite"' not in out                    # 未被錨點化
    assert 'href="#src-' not in out                     # 無死錨點
    assert "（來源①2）" in out                          # 原樣純文字降級
    # 同段內合法 cite 與混合 token 並存：合法者仍錨點、混合者仍純文字
    out2 = inline("正常（來源①）與混合（來源①2）並存")
    assert '<a class="cite" href="#src-1">（來源①）</a>' in out2
    assert "（來源①2）" in out2


def test_pure_number_over_20_and_circled_still_anchor():
    # 修後零回歸：（來源③）圈號、（來源21）純數字超 20 仍正常錨點化
    inline = R.make_inline("", src_ids={3, 21})
    assert '<a class="cite" href="#src-3">（來源③）</a>' in inline("見（來源③）")
    assert '<a class="cite" href="#src-21">（來源21）</a>' in inline("見（來源21）")


def test_f1_ultralong_number_no_crash_and_legit_still_anchor():
    # F1（Important）：超長純數字 citation（>int_max_str_digits=4300）修前撞 int() 拋 ValueError→整頁 render 崩；
    # 修後 cite_re 數字段限 1-4 位→不匹配→原樣純文字降級（＋cite_sub try/except 兜底），合法 cite 零回歸。
    inline = R.make_inline("", src_ids={1, 3, 21})
    payload = "（來源" + "1" * 5000 + "）"
    out = inline("前文" + payload + "後文")        # 不得拋例外
    assert 'class="cite"' not in out                # 未被錨點化
    assert 'href="#src-' not in out                 # 無死錨點
    assert payload in out                           # 原樣純文字降級
    # 合法 cite 仍正常錨點化（限長不誤傷 ≤4 位純數字／圈號）
    assert '<a class="cite" href="#src-3">（來源3）</a>' in inline("見（來源3）")
    assert '<a class="cite" href="#src-21">（來源21）</a>' in inline("見（來源21）")
    assert '<a class="cite" href="#src-1">（來源①）</a>' in inline("見（來源①）")
