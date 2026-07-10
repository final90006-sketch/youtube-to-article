# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "scripts" / "export_formats.py"


def _run(folder, *args):
    p = subprocess.run([sys.executable, str(EXPORT), str(folder), *args],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0
    assert "Traceback" not in (p.stdout + p.stderr)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines
    return json.loads(lines[-1])


def test_missing_transcript_json_returns_no_transcript_json(tmp_path):
    (tmp_path / "article.md").write_text("# 標題\n\n內容", encoding="utf-8")
    result = _run(tmp_path)
    assert result["ok"] is False
    assert result["reason"] == "NO_TRANSCRIPT"
    assert "article.obsidian.md" in result["written"]


def test_truncated_transcript_json_returns_no_transcript_json(tmp_path):
    (tmp_path / "transcript.json").write_text("{", encoding="utf-8")
    result = _run(tmp_path, "--srt")
    assert result["ok"] is False
    assert result["reason"] == "NO_TRANSCRIPT"


def test_bad_segment_t_is_skipped_without_crashing(tmp_path):
    (tmp_path / "transcript.json").write_text(json.dumps({
        "ok": True,
        "meta": {"title": "標題"},
        "track": {"source": "manual"},
        "segments": [{"t": "bad", "text": "壞時間"}, {"t": 2, "text": "正常時間"}],
    }, ensure_ascii=False), encoding="utf-8")
    result = _run(tmp_path, "--srt")
    assert result["ok"] is True
    assert "transcript.srt" in result["written"]
    assert "正常時間" in (tmp_path / "transcript.srt").read_text(encoding="utf-8")
