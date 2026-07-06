#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
export_formats.py — 把一個輸出夾的成果再匯出成常用格式：
  - transcript.srt / transcript.vtt   （由 transcript.json 逐字稿時間碼）
  - article.obsidian.md                （Obsidian 優化版：原生 callout、YT 時間碼可點、block-list frontmatter）
  - 送進 Obsidian vault（--vault auto，寫進 <vault>/影片文章/，依來源網址去重，並建立 Bases 視圖）

用法:
    python export_formats.py "<輸出夾>" [--srt] [--vtt] [--obsidian]
    python export_formats.py "<輸出夾>" --vault auto            # 自動偵測 vault → 送進「影片文章」夾
    python export_formats.py "<輸出夾>" --vault "<vault路徑>" --vault-folder "影片文章"
不指定格式旗標＝srt/vtt/obsidian 都產。只動指定夾與 vault 目標夾、不碰原檔。
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8")
    except Exception:
        pass

from common import SRC_MAP, TS_PAT as _TS_PAT_SRC, platform_plain  # noqa: E402（P0-3 常數收斂）

TS_PAT = re.compile(_TS_PAT_SRC)


# ---------------------------------------------------------------------------
# 字幕格式
# ---------------------------------------------------------------------------
def fmt_ts(sec, vtt=False):
    sec = max(0.0, float(sec or 0))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _cues(segments):
    segs = [(float(s.get("t", 0) or 0), (s.get("text") or "").strip())
            for s in segments if (s.get("text") or "").strip()]
    out = []
    for i, (t, txt) in enumerate(segs):
        end = segs[i + 1][0] if i + 1 < len(segs) else t + 4.0
        if end <= t:
            end = t + 1.0
        out.append((t, end, txt))
    return out


def to_srt(segments):
    lines = []
    for i, (a, b, txt) in enumerate(_cues(segments), 1):
        lines += [str(i), f"{fmt_ts(a)} --> {fmt_ts(b)}", txt, ""]
    return "\n".join(lines)


def to_vtt(segments):
    out = ["WEBVTT", ""]
    for a, b, txt in _cues(segments):
        out += [f"{fmt_ts(a, vtt=True)} --> {fmt_ts(b, vtt=True)}", txt, ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Obsidian 優化
# ---------------------------------------------------------------------------
def _yaml_str(v):
    # 雙引號內反斜線是 YAML 跳脫字元，會破 frontmatter → 一併處理；雙引號改單引號
    return '"' + str(v or "").replace("\\", "/").replace('"', "'").replace("\n", " ").strip() + '"'


def _ts_seconds(ts):
    try:
        parts = [int(p) for p in ts.split(":")]
        return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
    except Exception:
        return 0


def _remap_callouts(md):
    """把自訂 callout 換成 Obsidian 原生：[!key]→[!important]、[!warn]→[!warning]（[!note]/[!quote] 原生不動）。"""
    md = re.sub(r"(?m)^(\s*>\s*\[!)key(\])", r"\1important\2", md)
    md = re.sub(r"(?m)^(\s*>\s*\[!)warn(\])", r"\1warning\2", md)
    return md


def _linkify_timecodes(md, video_url):
    """YouTube 來源才做：[mm:ss] → [mm:ss](url?t=秒s)，已是連結（後面接 '('）則略過（可重複匯出）。"""
    if not video_url or not ("youtube.com" in video_url or "youtu.be" in video_url):
        return md

    def sub(m):
        end = m.end()
        if end < len(md) and md[end:end + 1] == "(":
            return m.group(0)
        sec = _ts_seconds(m.group(1))
        sep = "&" if "?" in video_url else "?"
        return f"[{m.group(1)}]({video_url}{sep}t={sec}s)"

    return TS_PAT.sub(sub, md)


def to_obsidian(article_md, meta, track, category, html_path=None):
    up = meta.get("upload_date") or ""
    published = f"{up[0:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else ""
    is_doc = (meta.get("type") or "av") == "document"   # schema v2：缺欄位＝av
    url = meta.get("webpage_url") or ""
    plat = platform_plain(url)
    cat = category if category and category not in ("YT影片文章", "未分類") else ""

    tags = ["影片文章"]      # 首項維持「影片文章」不動（分容器是 P2）
    if cat:
        tags.append(re.sub(r"\s+", "", cat))
    tags.append(plat)
    tag_block = "\n".join(f"  - {t}" for t in dict.fromkeys(tags))

    fm = ["---",
          f"title: {_yaml_str(meta.get('title'))}",
          "type: document-article" if is_doc else "type: video-article",
          f"source: {_yaml_str(url)}",
          f"author: {_yaml_str(meta.get('channel'))}"]
    if meta.get("channel_url"):
        fm.append(f"channel_url: {_yaml_str(meta.get('channel_url'))}")
    if published:
        fm.append(f"published: {published}")
    fm.append(f"created: {date.today().isoformat()}")
    if meta.get("duration_str"):
        fm.append(f"duration: {_yaml_str(meta.get('duration_str'))}")
    if meta.get("duration"):
        fm.append(f"duration_sec: {int(meta.get('duration'))}")
    fm.append(f"transcript_source: {_yaml_str(SRC_MAP.get(track.get('source'), track.get('source')))}")
    if meta.get("language"):
        fm.append(f"language: {_yaml_str(meta.get('language'))}")
    if cat:
        fm.append(f"category: {_yaml_str(cat)}")
    fm += ["tags:", tag_block, "---", ""]

    # 內文：原生 callout + （YouTube）時間碼可點
    body = _linkify_timecodes(_remap_callouts(article_md), url)

    # 來源 callout（放第一個 # 標題之後）
    src_bits = []
    if url:
        src_bits.append(f"[在{plat}開啟原片]({url})")
    if html_path:
        hp = "file:///" + str(html_path).replace("\\", "/")
        src_bits.append(f"[精緻閱讀版 HTML](<{hp}>)")
    if src_bits:
        callout = "> [!info] 來源　" + "　｜　".join(src_bits) + "\n\n"
        m = re.search(r"(?m)^#\s.*$", body)
        if m:
            body = body[:m.end()] + "\n\n" + callout + body[m.end():].lstrip("\n")
        else:
            body = callout + body

    return "\n".join(fm) + body


# ---------------------------------------------------------------------------
# 送進 vault
# ---------------------------------------------------------------------------
def detect_vault():
    """從 Obsidian 註冊檔找 vault 路徑（取 open 的，否則最近開的）。找不到回 None。"""
    try:
        reg = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
        data = json.loads(reg.read_text(encoding="utf-8"))
        vaults = data.get("vaults", {}) or {}
        if not vaults:
            return None
        items = list(vaults.values())
        opened = [v for v in items if v.get("open")]
        pick = (opened or sorted(items, key=lambda v: v.get("ts", 0), reverse=True))[0]
        return pick.get("path")
    except Exception:
        return None


def _safe_name(name, maxlen=90):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip()
    name = re.sub(r"\s+", " ", name).rstrip(". ")
    return (name[:maxlen].rstrip(". ") or "影片文章")


BASE_CONTENT = """filters:
  and:
    - file.inFolder("影片文章")
formulas:
  open: link(note.source, "🔗 開原片")
properties:
  note.author:
    displayName: 頻道／作者
  note.category:
    displayName: 分類
  note.type:
    displayName: 類型
  note.duration:
    displayName: 時長
  note.published:
    displayName: 發布
  note.created:
    displayName: 匯入
  formula.open:
    displayName: 原片
views:
  - type: table
    name: 全部（最新匯入在前）
    order:
      - file.name
      - author
      - category
      - duration
      - published
      - formula.open
    sort:
      - property: note.created
        direction: DESC
    limit: 500
  - type: table
    name: 依分類瀏覽
    groupBy:
      property: category
      direction: ASC
    order:
      - file.name
      - author
      - duration
      - formula.open
    sort:
      - property: note.created
        direction: DESC
    limit: 500
  - type: cards
    name: 卡片牆
    order:
      - file.name
      - author
      - category
    sort:
      - property: note.created
        direction: DESC
    limit: 200
"""


def write_to_vault(vault, folder, note_text, title, source_url):
    target = Path(vault) / folder
    target.mkdir(parents=True, exist_ok=True)

    # 依「來源網址」去重：刪掉舊的同來源筆記，確保一片一檔、重跑不長出「標題 1.md」
    if source_url:
        for f in target.glob("*.md"):
            try:
                head = f.read_text(encoding="utf-8")[:600]
            except Exception:
                continue
            if f'source: "{source_url}"' in head or f"source: {source_url}" in head:
                try:
                    f.unlink()
                except Exception:
                    pass

    fp = target / (_safe_name(title) + ".md")
    # utf-8-sig（含 BOM）：PowerShell 5.1 / 記事本等 ANSI 預設工具才不會把中文
    # frontmatter 讀成亂碼（交接 §九「?芸?摮?」bug 的根因＝無 BOM 被當 cp950 解）。
    # Obsidian 的 YAML 解析器會剝 BOM，實測不影響 properties。
    fp.write_text(note_text, encoding="utf-8-sig")

    # 首次：建立 Bases 視圖
    base_fp = target / "影片文章.base"
    if not base_fp.exists():
        base_fp.write_text(BASE_CONTENT, encoding="utf-8")
    return fp, base_fp.exists()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="輸出夾（內含 transcript.json / article.md）")
    ap.add_argument("--srt", action="store_true")
    ap.add_argument("--vtt", action="store_true")
    ap.add_argument("--obsidian", action="store_true")
    ap.add_argument("--vault", default=None, help='Obsidian vault 路徑，或 "auto" 自動偵測')
    ap.add_argument("--vault-folder", default="影片文章", help="送進 vault 的資料夾名（預設 影片文章）")
    args = ap.parse_args()
    d = Path(args.dir)
    plain = not (args.srt or args.vtt or args.obsidian)   # 未指定格式＝srt/vtt/obsidian 都產

    data = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    segments = data.get("segments", []) or []
    meta = data.get("meta", {}) or {}
    track = data.get("track", {}) or {}
    is_doc = (meta.get("type") or "av") == "document"   # schema v2：缺欄位＝av
    written = []
    skipped = []
    obsidian_text = None

    if (args.srt or plain) and segments:
        (d / "transcript.srt").write_text(to_srt(segments), encoding="utf-8")
        written.append("transcript.srt")
    if (args.vtt or plain) and segments:
        (d / "transcript.vtt").write_text(to_vtt(segments), encoding="utf-8")
        written.append("transcript.vtt")
    if (args.srt or args.vtt or plain) and not segments and is_doc:
        skipped.append("srt/vtt：document 型無逐字稿 segments，跳過字幕匯出")
    if (args.obsidian or plain or args.vault) and (d / "article.md").exists():
        art = (d / "article.md").read_text(encoding="utf-8")
        html_path = (d / "article.html") if (d / "article.html").exists() else None
        obsidian_text = to_obsidian(art, meta, track, d.parent.name, html_path)
        # utf-8-sig（含 BOM）：修交接 §九 frontmatter 亂碼（見 write_to_vault 註解）
        (d / "article.obsidian.md").write_text(obsidian_text, encoding="utf-8-sig")
        written.append("article.obsidian.md")

    result = {"ok": bool(written), "written": written, "dir": str(d)}
    if skipped:
        result["skipped"] = skipped

    if args.vault and meta.get("private"):
        # 敏感分流（F2）：private 不送 Obsidian vault（夾內 article.obsidian.md 照產，僅擋入庫）
        result["vault_error"] = "private 文檔不送 Obsidian vault"
    elif args.vault and obsidian_text:
        vault = detect_vault() if args.vault == "auto" else args.vault
        if not vault or not Path(vault).exists():
            result["vault_error"] = "找不到 Obsidian vault（請確認已開過 Obsidian，或用 --vault 指定路徑）"
        else:
            fp, base_ok = write_to_vault(vault, args.vault_folder, obsidian_text,
                                         meta.get("title") or d.name, meta.get("webpage_url") or "")
            result["vault_note"] = str(fp)
            result["vault_base"] = base_ok
    elif args.vault and not obsidian_text:
        result["vault_error"] = "找不到 article.md，無法送進 Obsidian"

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
