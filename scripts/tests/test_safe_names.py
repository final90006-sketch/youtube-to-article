# -*- coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import common as C


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher_safe_names", str(ROOT / "launcher.pyw"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load_launcher()


def test_common_safe_filename_reserved_and_illegal_chars():
    assert C.safe_filename("CON") == "_CON"
    assert C.safe_filename("PRN") == "_PRN"
    assert C.safe_filename('a<>:"/\\|?*b') == "ab"


def test_common_safe_filename_reserved_stem_with_extension():
    # F11（已修）：保留字.副檔名（aux.txt / con.md）的主檔名部分也要擋
    assert C.safe_filename("aux.txt").lower() == "_aux.txt"
    assert C.safe_filename("CON.md").lower() == "_con.md"
    assert C.safe_filename("正常標題.mp4") == "正常標題.mp4"   # 非保留字不受影響


def test_launcher_safe_cat_reserved_word():
    assert L.safe_cat("CON") == "_CON"
