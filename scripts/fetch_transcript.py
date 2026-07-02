#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch_transcript.py — 影片轉文章 技能的「抓取＋解析」引擎

只做一件事、做穩：給一個 YouTube 影片網址，
抓回「中繼資料 + 章節 + 最高品質的逐字字幕」，輸出乾淨的
transcript.json（給 Claude 寫文章用）與 transcript.txt（人可讀）。

設計原則（對齊 CLAUDE.md：精簡優先、外科手術式、嚴謹）：
- 字幕優先序：人工字幕 > 原語自動字幕 > 自動翻譯字幕（後者最不準）。
- json3 為主解析格式（順序事件、無滾動重複），vtt 為備援。
- 全程透明：把「選了哪條字幕、是不是人工、哪個語言」印出來，方便人工覆核。
- 絕不杜撰：抓不到就明白回報，不亂猜。

用法:
    python fetch_transcript.py "<youtube_url>" --out "<output_dir>" [--lang zh-Hant]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# Windows 主控台預設非 UTF-8，會讓中文日誌變亂碼；強制 UTF-8 輸出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from yt_dlp import YoutubeDL
except Exception as e:  # pragma: no cover
    print("[ERROR] 找不到 yt-dlp，請先執行： python -m pip install -U yt-dlp", file=sys.stderr)
    raise

# ---- 語言偏好（由高到低）。人工字幕一律優先於任何自動字幕。----
PREFERRED_LANGS = ["zh-Hant", "zh-TW", "zh", "zh-Hans", "zh-CN", "yue", "en"]


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def hms(seconds):
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def extract_video_id(url):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


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
# 字幕解析
# ---------------------------------------------------------------------------
def parse_json3(raw):
    """json3 → [(t_seconds, text)]。自動字幕在 json3 是順序事件，天然無滾動重複。"""
    data = json.loads(raw)
    out = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs)
        text = text.replace("​", "").strip()
        if not text:
            continue
        t = (ev.get("tStartMs", 0)) / 1000.0
        # 去掉與前一句完全相同的連續重複
        if out and out[-1][1] == text:
            continue
        out.append((t, text))
    return out


def _vtt_time(ts):
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
        else:
            h, m, s = "0", parts[0], parts[1]
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return 0.0


def parse_vtt(raw):
    """vtt 備援解析，含自動字幕滾動視窗去重（只保留每個 cue 的新增行）。"""
    lines = raw.splitlines()
    cues = []  # (start_seconds, [text_lines])
    i = 0
    cur_start = None
    cur_text = []
    tag_re = re.compile(r"<[^>]+>")
    time_re = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})\s*-->")
    while i < len(lines):
        line = lines[i]
        m = time_re.search(line)
        if m:
            if cur_start is not None and cur_text:
                cues.append((cur_start, cur_text))
            cur_start = _vtt_time(m.group(1))
            cur_text = []
        elif line.strip() and not line.strip().isdigit() and "WEBVTT" not in line \
                and not line.startswith(("Kind:", "Language:", "NOTE", "STYLE")):
            clean = tag_re.sub("", line).strip()
            if clean:
                cur_text.append(clean)
        i += 1
    if cur_start is not None and cur_text:
        cues.append((cur_start, cur_text))

    # 滾動去重：對每個 cue，只接受尚未出現在上一個 cue 的行
    out = []
    seen_prev = []
    for start, texts in cues:
        for t in texts:
            if t in seen_prev:
                continue
            if out and out[-1][1] == t:
                continue
            out.append((start, t))
        seen_prev = texts
    return out


# ---------------------------------------------------------------------------
# 字幕挑選
# ---------------------------------------------------------------------------
def base_lang(key):
    """把字幕鍵正規化成語言基底；中文區分繁/簡，其餘取連字號前的語言碼。
    例： 'en-j3PyPqV-e1s'→'en'、'en-orig'→'en'、'pt-BR'→'pt'、
         'zh-Hant'/'zh-TW'/'zh-HK'→'zh-Hant'、'zh-Hans'/'zh-CN'→'zh-Hans'、'zh-xxxx'→'zh'。"""
    if not key:
        return None
    k = key
    if k.startswith("zh") or k.startswith("yue"):
        if "Hant" in k or k in ("zh-TW", "zh-HK", "zh-MO") or k.startswith("yue"):
            return "zh-Hant"
        if "Hans" in k or k in ("zh-CN", "zh-SG"):
            return "zh-Hans"
        return "zh"
    return k.split("-")[0]


def _find_key(track_dict, target_base):
    """在 track_dict 中找出語言基底等於 target_base 的最佳鍵。
    偏好：精確碼 > '*-orig' > 最短鍵（通常最乾淨）。"""
    cands = [k for k in track_dict if base_lang(k) == target_base]
    if not cands:
        return None
    cands.sort(key=lambda k: (0 if k == target_base else (1 if k.endswith("-orig") else 2), len(k)))
    return cands[0]


def pick_track(subtitles, automatic, want_lang, original_lang):
    """
    回傳 (lang_code, fmt_list, source)，source ∈ {'manual','auto','auto-translated'}。
    嚴謹優先序（以「最忠實講者實際說的話」為準，翻譯交給 Claude）：
      0) 使用者 --lang 指定（人工 > 自動）
      1) 原語人工字幕      ← 最高保真
      2) 原語自動字幕
      3) 偏好語言人工字幕   ← 二手人工翻譯
      4) 偏好語言自動字幕（原語=auto；否則=auto-translated）
      5) 任一人工 / 任一自動
    """
    subtitles = subtitles or {}
    automatic = automatic or {}
    orig_base = base_lang(original_lang)

    # 建立偏好語言基底序列
    pref = []
    if want_lang:
        pref.append(base_lang(want_lang))
    if orig_base:
        pref.append(orig_base)
    for L in PREFERRED_LANGS:
        b = base_lang(L)
        if b not in pref:
            pref.append(b)

    # 0) 使用者指定語言
    if want_lang:
        wb = base_lang(want_lang)
        k = _find_key(subtitles, wb)
        if k:
            return k, subtitles[k], "manual"
        k = _find_key(automatic, wb)
        if k:
            return k, automatic[k], "auto" if wb == orig_base else "auto-translated"

    # 1) 原語人工字幕
    if orig_base:
        k = _find_key(subtitles, orig_base)
        if k:
            return k, subtitles[k], "manual"
    # 2) 原語自動字幕
    if orig_base:
        k = _find_key(automatic, orig_base)
        if k:
            return k, automatic[k], "auto"
    # 3) 偏好語言人工字幕
    for b in pref:
        k = _find_key(subtitles, b)
        if k:
            return k, subtitles[k], "manual"
    # 4) 偏好語言自動字幕
    for b in pref:
        k = _find_key(automatic, b)
        if k:
            return k, automatic[k], "auto" if b == orig_base else "auto-translated"
    # 5) 任一人工 / 任一自動
    if subtitles:
        k = next(iter(subtitles))
        return k, subtitles[k], "manual"
    if automatic:
        k = next(iter(automatic))
        return k, automatic[k], "auto-translated"
    return None, None, None


def fmt_url(fmt_list, prefer=("json3", "srv3", "vtt")):
    by_ext = {f.get("ext"): f for f in fmt_list if f.get("url")}
    for ext in prefer:
        if ext in by_ext:
            return ext, by_ext[ext]["url"]
    # 退而求其次：任何有 url 的
    for f in fmt_list:
        if f.get("url"):
            return f.get("ext"), f["url"]
    return None, None


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Podcast 連結正規化（讓「貼節目頁/單集頁」也能轉文章）
#   - Spotify：DRM，yt-dlp 無解 → 明確擋下並指路（別丟 stack trace）
#   - SoundOn / Firstory：單集頁是 JS 空殼，yt-dlp「Unsupported URL」→ 改用節目 RSS
#     精準對到「使用者貼的那一集」（epId/storyId 就藏在 feed 裡，實測可比對）
#   - 任何 RSS/訂閱源：extract 會回「整包多集清單」→ 由 --episode 取一集（預設最新）
# 設計：純標準庫（urllib+re），不加依賴；救不到就回明確原因，不杜撰、不亂猜集數。
# ---------------------------------------------------------------------------
SPOTIFY_MSG = ("Spotify 受 DRM 保護，無法下載或轉檔。請改貼這集的 "
               "Apple Podcasts 連結、節目 RSS（.xml / 直接的 .mp3），或 YouTube 連結。")
FIRSTORY_MSG = ("Firstory 單集頁無法直接擷取。請改貼：① 該集的 Apple Podcasts 連結、"
                "② 節目 RSS（feed.firstory.me/rss/user/<id>），或 ③ 該集的 YouTube 連結。")


def _is_feedish(url):
    """這個網址看起來像 RSS/訂閱源嗎？（用來決定要不要『只列清單不逐集解析』以免拖慢）"""
    u = (url or "").lower()
    if u.endswith(".xml") or u.endswith(".rss"):
        return True
    return any(k in u for k in ("/rss/user/", "/podcasts/", "podcast.xml", "format=rss",
                                "/feed.xml", "/rss.xml"))


def _looks_hashy(s):
    """標題看起來像檔名/雜湊（generic 抽取常見）→ 之後用 RSS 真標題覆蓋。"""
    s = (s or "").strip()
    if not s:
        return True
    if ".mp3" in s.lower() or ".m4a" in s.lower():
        return True
    return " " not in s and len(s) >= 18 and len(re.sub(r"[A-Za-z0-9_\-]", "", s)) == 0


def _rss_find_enclosure(feed_url, match_id, log):
    """抓 RSS feed，挑出「含 match_id 的那一集」（找不到就取最新）→ (enclosure_url, title)。"""
    try:
        xml = http_get(feed_url)
    except Exception as e:
        log(f"      取 RSS 失敗：{str(e)[:90]}")
        return None, None
    items = re.findall(r"<item\b.*?</item>", xml, re.S | re.I)
    if not items:
        return None, None
    chosen = None
    if match_id:
        for it in items:
            if match_id in it:
                chosen = it
                break
    if chosen is None:
        chosen = items[0]  # RSS 慣例：最新在最前
    enc = re.search(r'<enclosure\b[^>]*\burl=["\']([^"\']+)["\']', chosen, re.I)
    tm = re.search(r"<title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</title>", chosen, re.S | re.I)
    title = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else None
    return (enc.group(1) if enc else None), title


def _firstory_userid(story_url, log):
    """Firstory 單集頁 → 取 userId（og:image 的 /Avatar/<userId>/ 內含），組節目 RSS 用。"""
    try:
        page = http_get(story_url)
    except Exception as e:
        log(f"      取 Firstory 頁失敗：{str(e)[:90]}")
        return None
    m = re.search(r"/Avatar/([A-Za-z0-9]{16,})/", page)
    if m:
        return m.group(1)
    m = re.search(r"firstory\.me/(?:rss/)?user/([A-Za-z0-9]{16,})", page)
    return m.group(1) if m else None


def resolve_podcast_url(url, log):
    """把已知會卡住的 Podcast 連結轉成 yt-dlp 能吃的連結。
    回傳 (extract_url, title_hint, hard_fail)；hard_fail=(reason, message) 代表救不了、要明確擋下。
    其餘平台（YouTube/X/Apple 單集/SoundCloud/直連 mp3/RSS）原樣放行。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""

    # Spotify：DRM，無解 → 明確擋下並指路
    if host.endswith("spotify.com"):
        return None, None, ("SPOTIFY_DRM", SPOTIFY_MSG)

    # SoundOn 單集頁 → 從節目 RSS 精準對到該集（epId 就在 enclosure URL 內）
    m = re.search(r"player\.soundon\.fm/p/([A-Za-z0-9\-]+)(?:/episodes/([A-Za-z0-9\-]+))?", url)
    if m:
        pid, epid = m.group(1), m.group(2)
        feed = f"https://feeds.soundon.fm/podcasts/{pid}.xml"
        log(f"      SoundOn 單集頁 → 改用節目 RSS：{feed}")
        enc, title = _rss_find_enclosure(feed, epid, log)
        if enc:
            log(f"      對到單集：{title or enc[:70]}")
            return enc, title, None
        return feed, None, None  # 退一步：交給 feed 流程取最新

    # Firstory 單集頁 → 取 userId 組 RSS，再用 storyId 對到該集
    m = re.search(r"firstory\.me/story/([A-Za-z0-9\-]+)", url)
    if m:
        story_id = m.group(1)
        uid = _firstory_userid(url, log)
        if uid:
            feed = f"https://feed.firstory.me/rss/user/{uid}"
            log(f"      Firstory 單集頁 → 改用節目 RSS：{feed}")
            enc, title = _rss_find_enclosure(feed, story_id, log)
            if enc:
                log(f"      對到單集：{title or enc[:70]}")
                return enc, title, None
        return None, None, ("FIRSTORY_PAGE", FIRSTORY_MSG)

    return url, None, None


def pick_feed_entry(info, episode):
    """info 若是 RSS/feed 的多集清單 → 回傳 (entry_url, title, n, idx)；不是清單回 None；空清單 n=0。"""
    if not isinstance(info, dict):
        return None
    if not (info.get("_type") == "playlist" or info.get("entries") is not None):
        return None
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        return ("", None, 0, -1)
    n = len(entries)
    idx = min(max((episode or 1) - 1, 0), n - 1)
    entry = entries[idx]
    ent_url = entry.get("url") or entry.get("webpage_url") or entry.get("original_url")
    return (ent_url, entry.get("title"), n, idx)


# ---------------------------------------------------------------------------
# 財經科技詞庫：提升中文財經/科技 Podcast 的辨識（hotwords/initial_prompt）
#   ＋事後校正已知誤聽（correction_map）。詞庫缺檔時全部無痛略過、不影響原流程。
# ---------------------------------------------------------------------------
_LEXICON = None


def _load_lexicon():
    global _LEXICON
    if _LEXICON is not None:
        return _LEXICON
    _LEXICON = {"initial_prompt": None, "hotwords": None, "pairs": []}
    try:
        p = Path(__file__).resolve().parent.parent / "finance_tech_lexicon.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        _LEXICON["initial_prompt"] = data.get("initial_prompt") or None
        _LEXICON["hotwords"] = data.get("hotwords") or None
        cm = data.get("correction_map", {}) or {}
        # 長詞優先，避免「短誤聽」先把「長誤聽」的一部分換掉
        _LEXICON["pairs"] = sorted(cm.items(), key=lambda kv: -len(kv[0]))
    except Exception:
        pass
    return _LEXICON


def correct_terms(text):
    """用詞庫把 Whisper 逐字稿中『已知的財經/科技專有名詞誤聽』校正回正確繁中名。
    只取代詞庫內的已知字串（多為 >=3 字專有名詞），不動其餘一般中文。"""
    for wrong, right in _load_lexicon()["pairs"]:
        if wrong in text:
            text = text.replace(wrong, right)
    return text


# ---------------------------------------------------------------------------
# 無字幕備援：下載音訊 ＋ Whisper 語音辨識
# ---------------------------------------------------------------------------
def whisper_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def download_audio(url, outdir, log, cookies=None):
    """用 yt-dlp 抓最佳音訊串流，回傳音檔路徑（失敗回 None）。"""
    log("      下載音訊串流 …")
    for p in outdir.glob("_audio.*"):
        try:
            p.unlink()
        except Exception:
            pass
    out_tmpl = str(outdir / "_audio.%(ext)s")
    # Whisper 一律重採樣到 16kHz 單聲道，故偏好「較低位元率」音訊＝品質中性但下載/解碼更快
    cmd = [sys.executable, "-m", "yt_dlp", "--js-runtimes", "node",
           "-f", "bestaudio[abr<=129]/bestaudio/best", "-N", "4",
           "--no-playlist", "-o", out_tmpl, url]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    files = sorted(outdir.glob("_audio.*"))
    if files:
        f = files[0]
        log(f"      音訊：{f.name}（{f.stat().st_size // 1024:,} KB）")
        return f
    log("[WARN] 音訊下載失敗。")
    if proc.stderr:
        log("      " + proc.stderr.strip()[-300:])
    return None


def ytdlp_download_subs(url, outdir, langs, cookies, log):
    """用 yt-dlp 正規下載字幕檔（自動處理 m3u8/HLS 並轉成 vtt），解析回 [(t,text)]。
    用於：字幕網址其實是 m3u8 播放清單、直接 http_get 抓不到文字（常見於 X/Twitter）。"""
    for p in outdir.glob("_sub.*"):
        try:
            p.unlink()
        except Exception:
            pass
    want = ",".join(dict.fromkeys([l for l in langs if l])) or "en"
    cmd = [sys.executable, "-m", "yt_dlp", "--js-runtimes", "node",
           "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", want, "--convert-subs", "vtt",
           "--no-playlist", "-o", str(outdir / "_sub.%(ext)s"), url]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    log(f"      yt-dlp 下載字幕（langs={want}）…")
    _p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if _p.returncode != 0:                          # 區分「真的無字幕」與「下載失敗」，別靜默
        log(f"      [WARN] yt-dlp 字幕下載非零結束碼 {_p.returncode}：{(_p.stderr or '').strip()[:160]}")
    segs = []
    for f in sorted(outdir.glob("_sub*.vtt")):
        try:
            cand = parse_vtt(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            cand = []
        if cand and len(cand) > len(segs):
            segs = cand
    for p in outdir.glob("_sub.*"):
        try:
            p.unlink()
        except Exception:
            pass
    return segs


_TRANSCRIBER = None


def _register_nvidia_dlls():
    """Windows：把 pip 安裝的 CUDA DLL 目錄同時加進 add_dll_directory 與 PATH。
    （nvidia-*-cu12 wheel 的 .dll 在 nvidia/<lib>/bin；nvidia 是命名空間套件用 __path__；
    ctranslate2 的載入器只認 PATH，故兩者都要加；需 cublas＋cudnn＋cuda_runtime(cudart) 齊全才算 OK）。"""
    need = {"cublas", "cudnn", "cuda_runtime"}
    got = set()
    try:
        import nvidia
        for root in list(getattr(nvidia, "__path__", [])):
            for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
                d = os.path.join(root, sub, "bin")
                if os.path.isdir(d):
                    try:
                        os.add_dll_directory(d)
                    except Exception:
                        pass
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                    got.add(sub)
    except Exception:
        pass
    return need.issubset(got)


def build_transcriber(cpu_model, log):
    """偵測裝置→回傳 (transcribe_fn, device, model_label)，整個程序只建一次。
    GPU 可用：large-v3-turbo + float16 + 批次16（品質≥small 且快 5–10×）。
    否則：cpu_model（預設 small）+ int8 + 實體核數緒（品質維持原樣）。
    GPU 以「受時限保護的暖機」驗證，任何卡住/錯誤都乾淨退回 CPU，絕不卡死。"""
    global _TRANSCRIBER
    if _TRANSCRIBER is not None:
        return _TRANSCRIBER
    from faster_whisper import WhisperModel
    dlls_ok = _register_nvidia_dlls()  # 沒找到 cuBLAS/cuDNN DLL 就別碰 GPU，避免缺庫卡死
    force_cpu = bool(os.environ.get("VTP_FORCE_CPU"))  # OOM 後重試時強制走 CPU
    try:
        import ctranslate2
        if dlls_ok and not force_cpu and ctranslate2.get_cuda_device_count() > 0:
            log("      偵測到 GPU → 載入 large-v3-turbo（首次下載模型約 1.6GB，請稍候）…")
            # int8_float16＋不批次：品質仍 ≥ small，VRAM 用量低很多（避免 out of memory）
            model = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8_float16")
            import threading
            import numpy as np
            res = {}

            def _warm():
                try:
                    list(model.transcribe(np.zeros(16000, dtype="float32"), beam_size=1)[0])
                    res["ok"] = True
                except Exception as e:
                    res["err"] = e
            th = threading.Thread(target=_warm, daemon=True)
            th.start()
            th.join(timeout=150)  # 暖機逾時＝視為 GPU 不可用，退 CPU（防卡死）
            if not res.get("ok"):
                raise RuntimeError(res.get("err") or "GPU 暖機逾時")

            def tx(audio):
                return model.transcribe(str(audio), vad_filter=True, beam_size=1)
            log("      ✓ GPU 加速就緒（large-v3-turbo / int8_float16）")
            _TRANSCRIBER = (tx, "cuda", "large-v3-turbo")
            return _TRANSCRIBER
    except Exception as e:
        log(f"      GPU 不可用 → 改用 CPU（{type(e).__name__}: {str(e)[:80]}）")

    threads = min(os.cpu_count() or 8, 8)
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    log(f"      載入 CPU 模型 {cpu_model}（int8 / {threads} 緒）… 首次會下載模型")
    model = WhisperModel(cpu_model, device="cpu", compute_type="int8",
                         cpu_threads=threads, num_workers=1)

    def tx(audio):
        return model.transcribe(str(audio), vad_filter=True, beam_size=1)
    _TRANSCRIBER = (tx, "cpu", cpu_model)
    return _TRANSCRIBER


def _do_transcribe(tx, audio_path, duration, log, device, label):
    log(f"      開始辨識（{device} / {label}）…")
    segments, info = tx(audio_path)
    total = duration or getattr(info, "duration", 0) or 0
    out = []
    last = -1e9
    for seg in segments:  # 生成器：OOM 等錯誤會在這裡才丟出
        txt = (seg.text or "").strip()
        if txt:
            out.append((float(seg.start), correct_terms(txt)))
        if total and (seg.end - last) >= max(15.0, total / 25.0):
            last = seg.end
            pct = int(100 * seg.end / total)
            log(f"      辨識進度：{hms(seg.end)} / {hms(total)}（{pct}%）")
            log(f"@@PCT@@{pct}")  # 給 GUI 進度條解析用
    log(f"      辨識完成：語言={getattr(info, 'language', '?')}，共 {len(out)} 段。")
    return out, getattr(info, "language", None)


def whisper_transcribe(audio_path, cpu_model, duration, log):
    """用最佳裝置辨識；GPU 記憶體不足／任何 CUDA 錯誤 → 自動退回 CPU 重辨識（絕不讓整體失敗）。"""
    global _TRANSCRIBER
    tx, device, label = build_transcriber(cpu_model, log)
    try:
        return _do_transcribe(tx, audio_path, duration, log, device, label)
    except Exception as e:
        msg = str(e).lower()
        gpu_err = device == "cuda" and any(
            k in msg for k in ("out of memory", "oom", "cuda", "cublas", "cudnn", "gpu", "cudart"))
        if not gpu_err:
            raise
        log(f"      ⚠ GPU 失敗（{str(e)[:70]}）→ 釋放後改用 CPU 重新辨識")
        _TRANSCRIBER = None
        os.environ["VTP_FORCE_CPU"] = "1"  # 本程序後續一律走 CPU
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        tx2, d2, l2 = build_transcriber(cpu_model, log)
        return _do_transcribe(tx2, audio_path, duration, log, d2, l2)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=None, help="明確指定輸出資料夾")
    ap.add_argument("--base", default=None, help="輸出基底夾；自動建立 <base>/<標題>__<id>/")
    ap.add_argument("--lang", default=None, help="強制字幕語言（如 zh-Hant / en / ja）")
    ap.add_argument("--whisper", action="store_true", help="強制用語音辨識（不論有無字幕）")
    ap.add_argument("--no-whisper", action="store_true", help="無字幕時不要用語音辨識（維持舊行為，直接回報）")
    ap.add_argument("--whisper-model", default="small",
                    help="Whisper 模型大小：tiny/base/small(預設)/medium/large-v3，越大越準越慢")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="用瀏覽器登入態存取受限影片（chrome/firefox/edge）；X/Twitter 需登入時用")
    ap.add_argument("--episode", type=int, default=1,
                    help="貼節目 RSS/訂閱源時要取第幾集（1=最新，預設 1）")
    args = ap.parse_args()

    if not args.out and not args.base:
        log("[ERROR] 請提供 --out 或 --base 其中之一。")
        sys.exit(1)

    vid = extract_video_id(args.url) or "video"
    # base 模式下，真正的 outdir 要等拿到標題後才決定；先準備一個落腳處供早期錯誤寫入。
    if args.out:
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        err_dir = outdir
    else:
        base = Path(args.base)
        base.mkdir(parents=True, exist_ok=True)
        outdir = None
        err_dir = base

    base_opts = {
        "skip_download": True,
        "writesubtitles": False,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
    }

    def do_extract(url, cookies, flat=False):
        opts = dict(base_opts)
        if flat:
            opts["extract_flat"] = "in_playlist"
        if cookies:
            opts["cookiesfrombrowser"] = (cookies,)
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    log(f"[1/4] 解析影片資訊 …")
    cookies = args.cookies_from_browser  # 後續音訊下載也沿用

    # Podcast 連結正規化：Spotify(DRM) 明確擋下；SoundOn/Firstory 單集頁 → 節目 RSS 對到該集
    extract_url, title_hint, hard = resolve_podcast_url(args.url, log)
    if hard:
        reason, hint = hard
        (err_dir / f"_抓取失敗_{vid}.json").write_text(
            json.dumps({"ok": False, "reason": reason, "message": hint, "url": args.url},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "reason": reason, "message": hint}, ensure_ascii=False))
        log(f"[ERROR] {hint}")
        sys.exit(2)
    download_url = extract_url          # 真正要下載音訊的網址（feed 取集後會換成該集）
    feedish = _is_feedish(extract_url)

    try:
        info = do_extract(extract_url, cookies, feedish)
    except Exception as e:
        emsg = str(e)
        low = emsg.lower()
        # 疑似需登入且尚未帶 cookie → 自動用 Chrome 登入態重試一次（適用 X/Twitter 等）
        login_hint = any(k in low for k in [
            "log in", "login", "sign in", "not available", "nsfw", "authentication",
            "this tweet", "this post", "no video could be found", "rate limit", "could not find"])
        if not cookies and login_hint:
            log("      可能需要登入，改用 Chrome 登入態重試…")
            try:
                info = do_extract(extract_url, "chrome", feedish)
                cookies = "chrome"
            except Exception as e2:
                emsg = str(e2)
                low = emsg.lower()
                info = None
        else:
            info = None

        if info is None:
            reason, hint = "EXTRACT_FAILED", "無法取得影片資訊。"
            if "unavailable" in low:
                reason, hint = "VIDEO_UNAVAILABLE", "影片無法播放（可能下架、區域限制或年齡限制）。"
            elif "private" in low:
                reason, hint = "PRIVATE", "這是私人影片，無法存取。"
            elif "members-only" in low or "join this channel" in low:
                reason, hint = "MEMBERS_ONLY", "會員限定影片，無法存取。"
            elif any(k in low for k in ["log in", "login", "sign in", "nsfw", "authentication", "this post"]):
                reason, hint = "NEEDS_LOGIN", "這支影片需要登入才能存取（X/受限內容）。請先在 Chrome 登入該網站再試。"
            elif "age" in low:
                reason, hint = "AGE_RESTRICTED", "影片有年齡限制，需登入才能存取。"
            elif "unsupported url" in low or "no video could be found" in low:
                reason, hint = "UNSUPPORTED", ("這個連結無法擷取。若是 Podcast：請貼「單集」連結"
                    "（Apple Podcasts 含 ?i= 的網址、直接的 .mp3、或節目 RSS .xml）；"
                    "Spotify 不支援，請改貼 Apple Podcasts / RSS / YouTube 連結。")
            result = {"ok": False, "reason": reason, "message": hint, "error": emsg[:500], "url": args.url}
            (err_dir / f"_抓取失敗_{vid}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"ok": False, "reason": reason, "message": hint}, ensure_ascii=False))
            log(f"[ERROR] {hint}")
            sys.exit(2)

    # RSS/訂閱源：extract 回傳整包多集清單 → 依 --episode 取一集，再解析該集
    feed_pick = pick_feed_entry(info, args.episode)
    if feed_pick is not None:
        ent_url, ent_title, n, idx = feed_pick
        if n == 0:
            msg = "這個訂閱源（feed）裡找不到任何單集。"
            (err_dir / f"_抓取失敗_{vid}.json").write_text(
                json.dumps({"ok": False, "reason": "NO_EPISODES", "message": msg, "url": args.url},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"ok": False, "reason": "NO_EPISODES", "message": msg}, ensure_ascii=False))
            log(f"[ERROR] {msg}")
            sys.exit(2)
        if ent_title and not title_hint:
            title_hint = ent_title
        log(f"      這是含 {n} 集的訂閱源 → 取第 {idx + 1}/{n} 集：{ent_title or ent_url}")
        if ent_url:
            info = do_extract(ent_url, cookies, False)
            download_url = ent_url

    meta = {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "upload_date": info.get("upload_date"),  # YYYYMMDD
        "duration": info.get("duration"),
        "duration_str": hms(info.get("duration")),
        "view_count": info.get("view_count"),
        "webpage_url": info.get("webpage_url"),
        "language": info.get("language"),
        "description": info.get("description") or "",
    }
    chapters = []
    for c in (info.get("chapters") or []):
        chapters.append({
            "start": c.get("start_time"),
            "end": c.get("end_time"),
            "title": c.get("title"),
        })

    # generic 抽取常把標題弄成檔名/雜湊；若有 RSS 真標題就覆蓋（純顯示用，不影響音訊）
    if title_hint and ((not meta.get("title")) or _looks_hashy(meta.get("title"))):
        meta["title"] = title_hint

    log(f"      標題：{meta['title']}")
    log(f"      頻道：{meta['channel']}  時長：{meta['duration_str']}  章節：{len(chapters)}")

    # base 模式：拿到標題後才建立可讀的輸出資料夾（用平台真實 id 當後綴，跨站皆唯一）
    if outdir is None:
        sid = safe_filename(str(meta.get("id") or vid))[:40] or vid
        outdir = base / f"{safe_filename(meta['title'])}__{sid}"
        outdir.mkdir(parents=True, exist_ok=True)
        log(f"      輸出夾：{outdir}")

    lang = source = ext = None
    segs = None
    fmt_list = None
    whisper_model_used = None

    use_whisper = bool(args.whisper)
    if not use_whisper:
        log(f"[2/4] 挑選最佳字幕 …")
        lang, fmt_list, source = pick_track(
            info.get("subtitles"), info.get("automatic_captions"), args.lang,
            info.get("language"),
        )
        if not fmt_list:
            if args.no_whisper:
                result = {
                    "ok": False, "reason": "NO_SUBTITLES",
                    "message": "這部影片沒有任何可用字幕（人工或自動皆無）。",
                    "meta": meta,
                }
                (outdir / "transcript.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"ok": False, "reason": "NO_SUBTITLES"}, ensure_ascii=False))
                log("[ERROR] 找不到字幕。")
                sys.exit(2)
            log("      找不到字幕 → 改用語音辨識（Whisper）")
            use_whisper = True

    def _fail(reason, message, code=2):
        (outdir / "transcript.json").write_text(
            json.dumps({"ok": False, "reason": reason, "message": message, "meta": meta},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "reason": reason, "message": message}, ensure_ascii=False))
        log(f"[ERROR] {message}")
        sys.exit(code)

    def do_whisper():
        """下載音訊＋Whisper 辨識，回傳 (segs, lang, source, ext, model)。失敗則 _fail。"""
        log(f"[2/4] 語音辨識 …")
        if not whisper_available():
            _fail("NEEDS_WHISPER",
                  "需要語音辨識套件，請先安裝：python -m pip install -U faster-whisper")
        log(f"[3/4] 下載音訊並辨識 …")
        audio = download_audio(download_url, outdir, log, cookies)
        if not audio:
            _fail("AUDIO_FAILED", "無法下載這部影片的音訊串流，可能受限或網路問題。")
        wsegs, wlang = None, None
        try:
            wsegs, wlang = whisper_transcribe(audio, args.whisper_model, meta.get("duration"), log)
        except Exception as e:
            log(f"[ERROR] 語音辨識失敗：{e}")
        finally:
            try:
                audio.unlink()
            except Exception:
                pass
        if not wsegs:
            _fail("ASR_EMPTY", "語音辨識沒有產生任何文字（可能整片無語音/純音樂）。")
        return wsegs, (wlang or "auto"), "whisper", f"whisper-{args.whisper_model}", args.whisper_model

    if use_whisper:
        segs, lang, source, ext, whisper_model_used = do_whisper()
    else:
        ext, url = fmt_url(fmt_list)
        log(f"      選用：{lang}  來源：{source}  格式：{ext}")

        log(f"[3/4] 下載並解析字幕 …")
        raw = http_get(url)
        if ext == "json3":
            segs = parse_json3(raw)
        elif ext in ("vtt",):
            segs = parse_vtt(raw)
        else:
            try:
                segs = parse_json3(raw)
            except Exception:
                segs = parse_vtt(raw)

        if not segs:
            log("[WARN] 字幕直抓解析為空，換另一格式 …")
            ext2, url2 = fmt_url(fmt_list, prefer=("vtt", "srv3"))
            if url2 and url2 != url:
                segs = parse_vtt(http_get(url2))

        # 字幕網址可能是 m3u8 播放清單（X/Twitter 常見）→ 改用 yt-dlp 正規下載字幕檔
        if not segs:
            log("[WARN] 仍為空（疑似 m3u8/HLS 字幕）→ 改用 yt-dlp 下載字幕檔 …")
            segs = ytdlp_download_subs(
                download_url, outdir,
                [lang, args.lang, info.get("language"), "en", "zh-Hant", "zh-Hans"], cookies, log)
            if segs:
                ext = "vtt(yt-dlp)"

        # 字幕真的拿不到內容 → 退回語音辨識（除非明確 --no-whisper）
        if not segs:
            if args.no_whisper:
                _fail("SUBTITLE_EMPTY", "找到字幕軌但無法解析出任何內容，且已停用語音辨識。")
            log("[WARN] 字幕無法解析出內容 → 退回語音辨識（Whisper）")
            segs, lang, source, ext, whisper_model_used = do_whisper()

    full_text = " ".join(t for _, t in segs)
    word_count = len(full_text.split())
    char_count = len(full_text)

    track_info = {
        "lang": lang,
        "source": source,  # manual / auto / auto-translated / whisper
        "format": ext,
        "whisper_model": whisper_model_used,
        "original_language": info.get("language"),
        "available_manual": list((info.get("subtitles") or {}).keys()),
        "segments": len(segs),
        "word_count": word_count,
        "char_count": char_count,
    }

    # ---- 輸出 transcript.json（給 Claude 寫文章）----
    out_json = {
        "ok": True,
        "meta": meta,
        "chapters": chapters,
        "track": track_info,
        "segments": [{"t": round(t, 2), "text": txt} for t, txt in segs],
    }
    (outdir / "transcript.json").write_text(
        json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 輸出 transcript.txt（人可讀；每行帶 [mm:ss]，章節插入標頭）----
    lines = []
    lines.append(f"標題：{meta['title']}")
    lines.append(f"頻道：{meta['channel']}　時長：{meta['duration_str']}")
    lines.append(f"來源：{meta['webpage_url']}")
    lines.append(f"字幕：{lang}（{source}）　約 {char_count:,} 字 / {word_count:,} 詞")
    lines.append("=" * 60)
    ch_idx = 0
    chapter_starts = [(c["start"] or 0, c["title"]) for c in chapters]
    for t, txt in segs:
        while ch_idx < len(chapter_starts) and t >= chapter_starts[ch_idx][0]:
            lines.append("")
            lines.append(f"## [{hms(chapter_starts[ch_idx][0])}] {chapter_starts[ch_idx][1]}")
            lines.append("")
            ch_idx += 1
        lines.append(f"[{hms(t)}] {txt}")
    (outdir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")

    log(f"[4/4] 完成。逐字 {char_count:,} 字 / {word_count:,} 詞，{len(segs)} 段。")
    log(f"      → {outdir / 'transcript.json'}")
    log(f"      → {outdir / 'transcript.txt'}")

    # stdout 印出機器可讀的小結（給呼叫者判斷）
    print(json.dumps({
        "ok": True,
        "title": meta["title"],
        "channel": meta["channel"],
        "duration": meta["duration_str"],
        "lang": lang,
        "source": source,
        "chapters": len(chapters),
        "segments": len(segs),
        "char_count": char_count,
        "word_count": word_count,
        "out_dir": str(outdir),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
