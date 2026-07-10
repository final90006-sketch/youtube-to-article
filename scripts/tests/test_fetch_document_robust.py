# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_document as F


def test_read_text_best_decodes_utf8_cp950_utf16_and_skips_nul_misread(tmp_path):
    samples = {
        "u8.txt": ("繁體中文 utf8", "utf-8"),
        "cp950.txt": ("繁體中文 cp950", "cp950"),
        "u16.txt": ("繁體中文 utf16", "utf-16le"),
    }
    for name, (text, enc) in samples.items():
        p = tmp_path / name
        p.write_bytes(text.encode(enc))
        got = F.read_text_best(p)
        assert "繁體中文" in got
        assert "\x00" not in got


def test_bad_meta_title_filters_junk_and_keeps_normal_title():
    assert F._bad_meta_title("無題1") is True
    assert F._bad_meta_title("Untitled") is True
    assert F._bad_meta_title("Microsoft Word - x") is True
    assert F._bad_meta_title("正常標題") is False
