# -*- coding: utf-8 -*-
"""Task 3：launcher build_writer_prompt 多來源綜合 cite_rule＋單源位元組零回歸。

實際簽章（親讀 launcher.pyw:164 確認，非計畫示意）：
    build_writer_prompt(meta, transcript_txt, mode, is_asr, doc=False)
meta 為 dict（title/channel）；多源判定在 doc 分支開頭 multi = ('【來源' in transcript_txt)。
"""
import sys
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]   # skill 根（launcher.pyw 在此，非 scripts/）


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("launcher_t3", ROOT / "launcher.pyw")
_OLD_PATH = ROOT / "_backup_20260706" / "_p11_pre" / "launcher.pyw"   # 改動前基準
L_OLD = _load("launcher_t3_old", _OLD_PATH) if _OLD_PATH.exists() else None

# 多源＝正文含【來源①②③】分節（fetch_document --merge 產物）；單源無此標頭
MULTI_TXT = "標題：合併\n" + "=" * 10 + "\n【來源①：甲】\n\n甲文第一段。\n【來源②：乙】\n\n乙文第一段。"
SINGLE_TXT = "標題：單篇\n" + "=" * 10 + "\n單篇內容第一段。第二段。"
META = {"title": "合併測試", "channel": "測試作者"}


def _doc_prompt(mod, txt):
    return mod.build_writer_prompt(META, txt, "逐節精讀", False, doc=True)


def test_multi_prompt_has_synthesis_rule():
    p = _doc_prompt(L, MULTI_TXT)
    assert "綜合" in p and "（來源" in p          # 有綜合重組＋句末標號指示


def test_single_prompt_no_cite_rule():
    p = _doc_prompt(L, SINGLE_TXT)
    assert "（來源" not in p                        # 單源：零 citation 雜訊


@pytest.mark.skipif(L_OLD is None, reason="無 _backup_20260706 基準(私有內部檔,公開 repo 不含)")
def test_single_doc_prompt_byte_identical_to_backup():
    """紅線：同一份單源 doc transcript，改動後 prompt 與舊版逐字元完全一致（位元組零回歸）。"""
    assert _doc_prompt(L, SINGLE_TXT) == _doc_prompt(L_OLD, SINGLE_TXT)


@pytest.mark.skipif(L_OLD is None, reason="無 _backup_20260706 基準(私有內部檔,公開 repo 不含)")
def test_av_prompt_byte_identical_to_backup():
    """av（非 doc）分支未被觸碰：與舊版逐字元一致。"""
    new_av = L.build_writer_prompt(META, SINGLE_TXT, "逐節精讀", False, doc=False)
    old_av = L_OLD.build_writer_prompt(META, SINGLE_TXT, "逐節精讀", False, doc=False)
    assert new_av == old_av


def test_single_prompt_no_cite_rule_when_multi_false_despite_literal():
    """F2 修：單源文件內文含「【來源：X】」literal，multi 顯式 False → 不加 cite_rule（精確判定壓過 substring）。"""
    txt = "標題：單篇\n" + "=" * 10 + "\n本文引用某報告（【來源：主計總處】）佐證。第二段補充。"
    p = L.build_writer_prompt(META, txt, "逐節精讀", False, doc=True, multi=False)
    assert "（來源" not in p and "多來源綜合" not in p     # 精確 False → 零 citation 雜訊


def test_multi_none_falls_back_to_substring():
    """multi=None（未傳參）→ fallback 舊 substring 判定，相容無 sources 的呼叫點（含位元組零回歸依賴）。"""
    assert "綜合" in _doc_prompt(L, MULTI_TXT)            # None→substring→True
    assert "（來源" not in _doc_prompt(L, SINGLE_TXT)     # None→substring→False


def test_long_single_doc_with_source_literal_not_routed_multi(tmp_path, monkeypatch):
    """F2 修（截斷風險）：長單源文件含「【來源：X】」literal 但無 sources[] → 精確判定非 multi →
    不觸發『超長合併檔』強制單次退化警告（舊 substring bug 會誤判 multi 而印此警告、放棄單源分塊）。"""
    import json
    long_single = "引用（【來源：某報告】）。\n\n" + "內容段落。" * 13000    # >門檻、含 literal、無 sources
    assert len(long_single) > L.CHUNK_THRESHOLD_CHARS and "【來源" in long_single
    out = tmp_path / "o"; out.mkdir()
    (out / "transcript.txt").write_text(long_single, encoding="utf-8")
    (out / "transcript.json").write_text(json.dumps(
        {"ok": True, "meta": {"type": "document", "title": "單篇長文"}, "segments": [],
         "track": {"source": "document"}}, ensure_ascii=False), encoding="utf-8")   # 無 sources → 非 multi
    monkeypatch.setattr(L, "_write_single", lambda *a, **k: True)
    monkeypatch.setattr(L, "_write_long_article", lambda *a, **k: True)
    logs = []
    ok = L.write_article_via_claude(str(out), "逐節精讀", logs.append)
    assert ok is True
    assert not any("超長合併檔" in m for m in logs)      # 修前會印此警告（誤判 multi）；修後不印


def test_decision4_long_merge_forces_single_no_charsplit(tmp_path, monkeypatch):
    """決策4：doc＋multi＋逐字>CHUNK_THRESHOLD → 走單次、禁純字數切塊（不呼叫 _split_segments）、印警告。
    F2 修後 multi 改由 sources[] 精確判定，故 fixture 補上真實 merge 產物的頂層 sources（≥2）。"""
    import json
    long_merge = ("【來源①：甲】\n\n" + "甲" * 13000 +
                  "\n\n【來源②：乙】\n\n" + "乙" * 13000)          # ~26000 字 > 24000 門檻
    assert len(long_merge) > L.CHUNK_THRESHOLD_CHARS and "【來源" in long_merge
    out = tmp_path / "o"; out.mkdir()
    (out / "transcript.txt").write_text(long_merge, encoding="utf-8")
    (out / "transcript.json").write_text(json.dumps(
        {"ok": True, "meta": {"type": "document", "title": "合併"}, "segments": [],
         "track": {"source": "document"},
         "sources": [{"n": 1, "mark": "①", "title": "甲"},
                     {"n": 2, "mark": "②", "title": "乙"}]}, ensure_ascii=False), encoding="utf-8")

    calls = {"single": 0, "long": 0, "split": 0}
    monkeypatch.setattr(L, "_write_single", lambda *a, **k: calls.__setitem__("single", calls["single"] + 1) or True)
    monkeypatch.setattr(L, "_write_long_article", lambda *a, **k: calls.__setitem__("long", calls["long"] + 1) or True)
    monkeypatch.setattr(L, "_split_segments", lambda *a, **k: calls.__setitem__("split", calls["split"] + 1) or [])
    logs = []
    ok = L.write_article_via_claude(str(out), "逐節精讀", logs.append)

    assert ok is True
    assert calls["single"] == 1                 # 走單次撰寫
    assert calls["long"] == 0                    # 未走分塊長文路徑
    assert calls["split"] == 0                   # 未做純字數切塊（紅線：會切過來源標頭→標錯號）
    assert any("超長合併檔" in m for m in logs)    # 有退化警告
