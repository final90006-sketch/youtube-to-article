# -*- coding: utf-8 -*-
# scripts/tests/test_lint_article.py
# 驗證 lint_article.py（從 launcher.pyw 抽出的獨立產後完整性審計 CLI）：
#   (a) 含佔位搪塞語的 article.md → 偵測到 WARN／佔位項
#   (b) 乾淨完整的 article.md → 全 PASS
#   (c) transcript.json 有章節但文章漏寫某段時間範圍 → 該塊時間覆蓋 WARN（驗證多塊審計路徑非裝飾）
# 一律用 tmp_path 合成測試資料，不碰真庫。
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lint_article as L


def _write_transcript(folder, segments, chapters=None, doc_type="av"):
    data = {
        "ok": True,
        "meta": {"title": "測試", "channel": "測試頻道", "type": doc_type},
        "chapters": chapters or [],
        "track": {"source": "manual"},
        "segments": segments,
    }
    (folder / "transcript.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_placeholder_article_flags_warn(tmp_path):
    segments = [{"t": i * 30, "text": "逐字稿內容" * 20} for i in range(20)]
    _write_transcript(tmp_path, segments)
    article = (
        "# 測試\n\n## 重點\n"
        "這裡有內容但後面（後略），其餘同上，詳見正文，以下省略。"
    )
    (tmp_path / "article.md").write_text(article, encoding="utf-8")

    result = L.lint_article(tmp_path)
    assert result is not None
    assert result["warn_count"] > 0

    ph_check = next(c for c in result["checks"] if c["name"] == "佔位搪塞語黑名單")
    assert ph_check["status"] == "WARN"
    assert "見正文" in ph_check["detail"]
    assert "以下省略" in ph_check["detail"]
    assert "（後略）" in ph_check["detail"]
    assert "其餘同上" in ph_check["detail"]

    # 退出碼精神：只報不擋 —— lint_article() 本身不拋例外、不因 WARN 而回傳 None
    assert result["folder"] == str(tmp_path)


def test_clean_full_article_passes_everything(tmp_path):
    segments = [{"t": i * 30, "text": "逐字稿內容說明重點與細節。" * 15} for i in range(40)]
    chapters = [{"title": "第一章", "start": 0}, {"title": "第二章", "start": 600}]
    _write_transcript(tmp_path, segments, chapters=chapters)

    parts = ["# 測試\n\n## 💡 重點洞察\n- 洞察 [0:00]\n\n## ⚡ 可應用\n- 行動 [0:30]\n\n---\n"]
    t = 0
    for i in range(40):
        parts.append(f"## 第 {i} 小節 [{t // 60}:{t % 60:02d}]\n\n"
                      + ("完整撰寫的正文內容，涵蓋逐字稿的重點與細節說明。" * 8))
        t += 30
    parts.append("## ❝ 金句\n> 一句金句 [19:30]\n\n## 🧠 自我檢核\n- 問題？｜答案\n")
    (tmp_path / "article.md").write_text("\n".join(parts), encoding="utf-8")

    result = L.lint_article(tmp_path)
    assert result is not None
    assert result["warn_count"] == 0
    assert all(c["status"] == "PASS" for c in result["checks"])
    # format_report 不應拋例外、且能反映「全部通過」
    assert "全部通過" in L.format_report(result)


def test_missing_time_chunk_coverage_flags_that_chunk(tmp_path):
    # 兩個章節、時間範圍相距很遠；文章只寫到第一章的時間碼，完全沒提第二章 → 第二塊該被 WARN
    segments = [{"t": i * 30, "text": "內容" * 50} for i in range(400)]  # 0 ~ 11970 秒
    chapters = [{"title": "第一章", "start": 0}, {"title": "第二章", "start": 6000}]
    _write_transcript(tmp_path, segments, chapters=chapters)

    parts = ["# 缺塊測試\n"]
    for i in range(0, 2000, 30):     # 只覆蓋到 2000 秒，第二章（6000 秒起）完全沒提到
        parts.append(f"## 段落 [{i // 60}:{i % 60:02d}]\n" + ("完整內容敘述。" * 30))
    (tmp_path / "article.md").write_text("\n".join(parts), encoding="utf-8")

    result = L.lint_article(tmp_path)
    assert result is not None
    coverage_checks = [c for c in result["checks"] if "塊時間覆蓋" in c["name"]]
    assert len(coverage_checks) >= 2
    assert any(c["status"] == "WARN" for c in coverage_checks)
    assert coverage_checks[0]["status"] == "PASS"   # 第一塊（時間 0 附近）確實有覆蓋


def test_missing_article_md_returns_none(tmp_path):
    # 資料夾存在但沒有 article.md → 用法錯誤，回傳 None（由 CLI 端轉成退出碼 2）
    assert L.lint_article(tmp_path) is None


def test_no_transcript_json_still_runs_basic_checks(tmp_path):
    # 沒有 transcript.json：只做基本長度／結構／佔位審計，不應報例外
    (tmp_path / "article.md").write_text("# 標題\n\n## 內容\n" + ("完整內容。" * 40), encoding="utf-8")
    result = L.lint_article(tmp_path)
    assert result is not None
    names = [c["name"] for c in result["checks"]]
    assert "佔位搪塞語黑名單" in names
    assert any("無 transcript.json" in n for n in result["notes"])
