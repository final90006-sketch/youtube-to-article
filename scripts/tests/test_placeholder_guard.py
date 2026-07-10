# -*- coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher_placeholder", str(ROOT / "launcher.pyw"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load_launcher()


def _article(extra):
    body = "完整內容。" * 80
    return f"# 標題\n\n## 💡 重點洞察\n- 洞察\n\n## ⚡ 可應用 / 帶得走的行動\n- 行動\n\n{body}\n{extra}"


def test_find_placeholders_detects_blacklist_sample():
    assert "見正文" in L._find_placeholders("這段見正文後續補上")
    assert "以下省略" in L._find_placeholders("完整內容以下省略")


def test_validate_article_rejects_placeholder_and_accepts_clean_article():
    assert L._validate_article(_article("見正文")) == "PLACEHOLDER"
    assert L._validate_article(_article("收束段落。")) is None
