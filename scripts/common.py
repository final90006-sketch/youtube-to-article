#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
common.py — 影片轉文章 管線共用常數與小工具（P0-3 常數收斂：單一定義處）

之前 SRC_MAP／_platform／TS_PAT 散落在 render_html / build_index / export_formats /
derive_extras / launcher 各自定義，schema v2（type: av|document）之後每加一種來源
就要改 4-5 處。本檔是唯一定義處；各腳本一律 `from common import …`。

注意（零回歸鐵則）：本檔所有字面值都必須與收斂前各檔的原字面值一致——
render_html 的 hero 標籤與 build_index 的卡片標籤歷史上就長得不一樣，
所以分成 SRC_MAP（短標籤）與 SRC_MAP_HERO（長標籤）兩份，不可合併。
"""

import re

# ---------------------------------------------------------------------------
# Windows 合法檔名清洗（P0-1：字面值與 fetch_transcript.py 的原函式完全一致；
# fetch_transcript 為 av 零回歸保留自己那份，fetch_document 等新腳本一律 import 這份）
# ---------------------------------------------------------------------------
_WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_filename(name, maxlen=80):
    """轉成 Windows 合法資料夾名：去掉 <>:\"/\\|?* 與控制字元、避開保留字、截長。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip()
    name = re.sub(r"\s+", " ", name)
    name = name.rstrip(". ")
    name = (name[:maxlen].rstrip(". ") or "影片")
    if name.lower() in _WIN_RESERVED:               # Windows 保留字當資料夾名會 mkdir 失敗
        name = "_" + name
    return name


# ---------------------------------------------------------------------------
# 來源代碼 → 中文標籤（超集：影音字幕 + 文檔來源）
#   - 短標籤：build_index 卡片、export_formats（Obsidian frontmatter）用
#   - 未知鍵一律原樣顯示（消費端沿用 SRC_MAP.get(src, src) 慣例）
# ---------------------------------------------------------------------------
SRC_MAP = {
    "manual": "人工字幕",
    "auto": "自動字幕",
    "auto-translated": "自動翻譯",
    "whisper": "語音辨識",
    # ---- schema v2：文檔來源（P0-2）----
    "pdf": "PDF 文件",
    "web": "網頁文章",
    "md": "Markdown 文件",
    "txt": "文字文件",
    "docx": "Word 文件",
    "mixed": "多來源合併",   # fetch_document --merge 多來源（F6）；未知鍵原樣顯示慣例不變
}

# render_html hero 用的長標籤（歷史字面值，為 av 零回歸原樣保留；文檔鍵沿用短標籤）
SRC_MAP_HERO = dict(SRC_MAP)
SRC_MAP_HERO.update({
    "auto": "自動字幕（原語）",
    "auto-translated": "自動翻譯字幕",
    "whisper": "語音辨識（Whisper）",
})

# ---------------------------------------------------------------------------
# 時間碼 regex（正典＝render_html.py 舊 L38 版）
#   TS_PAT  ：整個時間碼一組（"[12:34]" → "12:34"），搭 ts_to_seconds() 用
#   TS_PAT3 ：時/分/秒分開捕捉（derive_extras、launcher 品質審計的歷史寫法）
# 兩者匹配的字串集合完全相同，只差捕捉組結構。
# ---------------------------------------------------------------------------
TS_PAT = r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]"
TS_PAT3 = r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]"


def ts_to_seconds(ts):
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return parts[0] * 60 + parts[1]


def hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


# ---------------------------------------------------------------------------
# 平台徽章
# ---------------------------------------------------------------------------
def platform_label(url, doc_type=None, source=None):
    """知識總覽卡片用的平台徽章（含 emoji；字面值＝build_index 舊 _platform）。
    doc_type=="document" 時依 track.source 分流（P0-2）。"""
    if doc_type == "document":
        if source == "pdf":
            return "📄 PDF"
        if source == "web":
            return "🌐 文章"
        return "📄 文件"
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "▶ YouTube"
    if any(k in u for k in ("podcasts.apple", "soundcloud", "firstory", "soundon", ".mp3", "rss")):
        return "🎙 Podcast"
    if "x.com" in u or "twitter.com" in u:
        return "𝕏 貼文"
    if "vimeo" in u:
        return "▶ Vimeo"
    return "▶ 影片"


def platform_plain(url):
    """Obsidian frontmatter/tag 用的純文字平台名（字面值＝export_formats 舊 _platform）。"""
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "podcasts.apple" in u:
        return "Podcast"
    if "soundcloud" in u:
        return "SoundCloud"
    if any(k in u for k in ("firstory", "soundon", "spotify", "rss", ".mp3")):
        return "Podcast"
    if "x.com" in u or "twitter.com" in u:
        return "X"
    if "vimeo" in u:
        return "Vimeo"
    return "影片"
