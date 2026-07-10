# -*- coding: utf-8 -*-
"""Task 1：fetch_document --merge 時多存結構化 sources[]；單源/非 merge 無此 key。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_document as FD


def _run(tmp, inputs, merge):
    import argparse
    ns = argparse.Namespace(inputs=[str(p) for p in inputs], merge=merge, base=None,
                            out=str(tmp), category=None, title=None, private=False, date=None)
    return FD.run(ns)


def test_merge_writes_sources_array(tmp_path):
    a = tmp_path / "a.md"; a.write_text("# 甲\n甲的內容第一段。", encoding="utf-8")
    b = tmp_path / "b.md"; b.write_text("# 乙\n乙的內容第一段。", encoding="utf-8")
    out = tmp_path / "o"; _run(out, [a, b], merge=True)
    data = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    assert "sources" in data and len(data["sources"]) == 2
    s0 = data["sources"][0]
    assert s0["n"] == 1 and s0["mark"] == "①" and "甲的內容" in s0["text"]
    assert data["sources"][1]["mark"] == "②"
    # meta 不被污染、schema 相容
    assert data["meta"]["type"] == "document" and "sources" not in data["meta"]


def test_single_input_no_sources_key(tmp_path):
    a = tmp_path / "a.md"; a.write_text("# 甲\n內容。", encoding="utf-8")
    out = tmp_path / "o"; _run(out, [a], merge=False)
    data = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    assert "sources" not in data          # 單源：位元組級與舊契約一致
