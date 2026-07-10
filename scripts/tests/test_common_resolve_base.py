# -*- coding: utf-8 -*-
"""F4：common.resolve_base 對 base_path.txt 的韌性（UTF-8 BOM／前後引號／讀取失敗）。

resolve_base 以 Path(__file__).parent.parent / base_path.txt 定位設定檔；
本測試 monkeypatch common.__file__ 指到 tmp，故完全不碰真實 base_path.txt。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
import common


def test_resolve_base_strips_bom_and_quotes(tmp_path, monkeypatch):
    # 舊碼 read_text("utf-8").strip()：BOM(﻿) 與包住路徑的引號都清不掉 → 路徑錯。
    target = tmp_path / "我的知識庫"
    (tmp_path / "base_path.txt").write_bytes(
        ('"' + str(target) + '"  \n').encode("utf-8-sig"))          # BOM＋雙引號＋尾端空白
    monkeypatch.setattr(common, "__file__", str(tmp_path / "scripts" / "common.py"))
    assert common.resolve_base() == target                          # 清乾淨 → 解析正確


def test_resolve_base_strips_single_quotes(tmp_path, monkeypatch):
    target = tmp_path / "另一庫"
    (tmp_path / "base_path.txt").write_text("'" + str(target) + "'\n", encoding="utf-8")
    monkeypatch.setattr(common, "__file__", str(tmp_path / "scripts" / "common.py"))
    assert common.resolve_base() == target


def test_resolve_base_fallback_when_missing(tmp_path, monkeypatch):
    # 無 base_path.txt（如公開 repo）→ 退回舊預設，且不拋例外。
    monkeypatch.setattr(common, "__file__", str(tmp_path / "scripts" / "common.py"))
    assert common.resolve_base() == Path.home() / "Desktop" / "YT影片文章"


def test_resolve_base_plain_path_unchanged(tmp_path, monkeypatch):
    # 零回歸：無 BOM／無引號的乾淨路徑，解析結果與內容一致。
    target = tmp_path / "乾淨庫"
    (tmp_path / "base_path.txt").write_text(str(target), encoding="utf-8")
    monkeypatch.setattr(common, "__file__", str(tmp_path / "scripts" / "common.py"))
    assert common.resolve_base() == target
