#!/usr/bin/env pythonw
# -*- coding: utf-8 -*-
"""
影片轉文章 — 桌面啟動器（專業版 GUI，支援批次；免費版用使用者現有的 Claude Code）

貼一支或多支影片網址（一行一個）→ 選分類 → 開始作業：
  逐一：fetch_transcript.py 抓字幕／（無字幕自動語音辨識，有 GPU 自動加速）
       → 背景 claude -p 精讀成 article.md → 本機渲染 article.html（不開終端機）
       → 歸入桌面分類夾並更新「知識總覽」。中途失敗自動跳過續跑，最後給總結。

界面：customtkinter（navy/gold 深色精緻）＋佇列狀態清單＋即時進度條。
自我測試：  pythonw launcher.pyw --selftest "<url>" [--write]   /   --smoketest
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
FETCH = SKILL_DIR / "scripts" / "fetch_transcript.py"
RENDER = SKILL_DIR / "scripts" / "render_html.py"
INDEX = SKILL_DIR / "scripts" / "build_index.py"
EXPORT = SKILL_DIR / "scripts" / "export_formats.py"
DERIVE = SKILL_DIR / "scripts" / "derive_extras.py"
THEME = SKILL_DIR / "brand_navy.json"
BASE = Path(os.path.expanduser("~")) / "Desktop" / "YT影片文章"
CATS_FILE = SKILL_DIR / "categories.json"
DEFAULT_CATS = ["投資理財", "法律", "科技AI", "健康", "學習成長", "時事評論", "其他"]
PY = sys.executable
CLAUDE = shutil.which("claude") or "claude"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

NAVY, NAVY_HOVER, DEEP = "#1B2A4A", "#24375E", "#13203A"
GOLD, GOLD_HOVER = "#B8932E", "#CCA53A"
CARD, CARD_BORDER, FIELD = "#1F3050", "#2C4068", "#16233D"
TXT_HI, TXT_LO = "#EAF0F8", "#9FB0C9"
GREEN, RED = "#37C281", "#E0707A"


def load_cats():
    cats, last = [], ""
    try:
        d = json.loads(CATS_FILE.read_text(encoding="utf-8"))
        cats = list(d.get("cats") or [])
        last = d.get("last") or ""
    except Exception:
        pass
    for c in DEFAULT_CATS:
        if c not in cats:
            cats.append(c)
    return cats, last


def save_cats(cats, last):
    try:
        CATS_FILE.write_text(json.dumps({"cats": cats, "last": last}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    except Exception:
        pass


def safe_cat(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (name or "").strip()).strip(". ")
    return name or "未分類"


def run_build_index(log=lambda s: None):
    try:
        subprocess.run([PY, str(INDEX), "--base", str(BASE)],
                       creationflags=NO_WINDOW, capture_output=True)
    except Exception as e:
        log(f"（知識總覽更新失敗：{e}）")


# ---------------------------------------------------------------------------
# 核心（與 GUI 解耦）
# ---------------------------------------------------------------------------
def run_fetch(url, lang=None, model=None, base=None, log=lambda s: None, ctrl=None):
    cmd = [PY, str(FETCH), url, "--base", str(base or BASE)]
    if lang:
        cmd += ["--lang", lang]
    if model:
        cmd += ["--whisper-model", model]
    log("正在連線 …")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW, bufsize=1)
    if ctrl is not None:
        ctrl["proc"] = proc
    info = None
    for line in proc.stdout:
        if ctrl is not None and ctrl["cancel"].is_set():
            try:
                proc.terminate()
            except Exception:
                pass
            break
        s = line.rstrip("\n")
        if not s.strip():
            continue
        if s.lstrip().startswith("{"):
            try:
                info = json.loads(s.strip())
                continue
            except Exception:
                pass
        log(s.strip())
    proc.wait()
    if ctrl is not None:
        ctrl["proc"] = None
        if ctrl["cancel"].is_set():
            return {"ok": False, "reason": "CANCELLED", "message": "已取消"}
    if info is None:
        info = {"ok": False, "reason": "UNKNOWN", "message": "抓取未回傳結果，請確認網址是否正確。"}
    return info


def build_writer_prompt(meta, transcript_txt, mode, is_asr):
    title = meta.get("title", "")
    channel = meta.get("channel", "")
    asr_note = ("（這支影片／這集 Podcast 沒有字幕，逐字稿由語音辨識產生，可能有錯字／斷句錯：請在文章開頭用一句 "
                "> [!warn] 註明，並對明顯口誤合理修正但不改變原意）\n" if is_asr else "")
    return (
        "你是把影片／Podcast 逐字稿『精讀』成一篇繁體中文長文的編輯。立場是精讀、不是摘要：寧長毋短、寧詳毋略。\n\n"
        "鐵則：\n"
        "1. 忠實不杜撰：只寫逐字稿講過的；不補外部知識、不臆測。講者意見寫『他主張／他認為』。\n"
        "2. 完整保留細節（對抗摘要太短）：每個論點、例子、數據、步驟、推理、轉折都要落進文章；沒看過的人讀完能掌握約 95% 實質內容。\n"
        "3. 不是逐字貼：去掉口水詞與重複，把口語重組成通順書面段落，但資訊點一個都不能少。\n"
        "4. 繁體中文輸出；原片非中文就忠實翻譯，專有名詞／人名／書名首次出現括號附原文。\n"
        "5. 不截斷：絕不用『（後略）』『以下省略』；長就寫完整部。\n\n"
        "結構（務必照用這些標題字串，程式會自動做成卡片／清單；emoji 要保留）：\n"
        "# 標題（用下方提供的標題）\n"
        "## 💡 重點洞察  → 3–6 條『一句話』洞察，每條一個「- 」，可帶 [時間碼]\n"
        "## ⚡ 可應用 / 帶得走的行動  → 3–8 條『明天就能做』的具體可執行行動，每條「- 」，附 [時間碼]\n"
        "---\n"
        "## 章節標題 [mm:ss]  → 依逐字稿章節切；無章節自行每 5–10 分鐘一節；每節開頭標 [mm:ss]；重要原話用「> 引言」\n"
        "## ❝ 金句  → 3–5 句最有力的原話，每句一行「> 引言」，附 [時間碼]\n"
        "## 🧠 自我檢核  → 選用：3–6 題，每行『- 問題？｜答案』（用全形｜分隔），給讀者複習\n"
        "## 關鍵結論 / 名詞解釋  → 視內容加\n\n"
        "正文可用強調框：> [!key] 重點 / > [!warn] 注意 / > [!note] 提示。時間碼用 [mm:ss] 或 [h:mm:ss]，取自逐字稿真實時間。\n"
        f"深度：{mode}（逐節精讀＝最完整；快覽＝只洞察＋行動＋各章兩三句；逐字精修＝接近逐字、去口水詞補標點）。\n"
        + asr_note +
        "\n只輸出 Markdown 本文，第一個字元就是「#」。不要任何前言、結語、解說，也不要用 ``` 圍欄。\n\n"
        f"標題：{title}\n頻道／節目：{channel}\n\n"
        "==== 以下為逐字稿（含時間碼與章節）====\n" + transcript_txt
    )


def _strip_and_extract(raw):
    """清掉 ``` 圍欄與前言：若開頭不是標題，砍到第一個 #/##/### 標題行開始（容忍 claude 偶爾加前言）。"""
    a = (raw or "").strip()
    if a.startswith("```"):
        a = re.sub(r"^```[a-zA-Z]*\n", "", a)
        a = re.sub(r"\n```\s*$", "", a).strip()
    if not a.startswith("#"):
        m = re.search(r"(?m)^#{1,3}\s", a)
        if m:
            a = a[m.start():].strip()
    return a


def _validate_article(a):
    """回問題代碼：None=通過 / EMPTY（空·錯誤訊息·過短）/ INCOMPLETE（缺必備區塊）。"""
    if len(a) < 200 or not a.startswith("#"):
        return "EMPTY"
    has_insight = ("重點洞察" in a) or ("關鍵洞察" in a)
    has_action = ("可應用" in a) or ("帶得走" in a) or ("可帶走" in a) or ("行動" in a)
    if not (has_insight and has_action):
        return "INCOMPLETE"
    if _find_placeholders(a):
        return "PLACEHOLDER"
    return None


def _looks_auth_error(raw, err):
    s = ((raw or "") + " " + (err or "")).lower()
    # 「401」要與認證字眼同現才算（避免文章內容碰巧含 401 被誤判）
    return ("authenticate" in s) or ("invalid api key" in s) or \
           ("invalid authentication" in s) or ("please run /login" in s) or \
           ("oauth" in s and "expired" in s) or \
           ("401" in s and ("auth" in s or "unauthor" in s or "credential" in s or "api key" in s))


def _run_claude_once(prompt, ctrl, timeout=2400):
    """跑一次 claude -p，回 (stdout, stderr, returncode, timed_out)。逾時會殺掉子行程避免殭屍洩漏。"""
    proc = subprocess.Popen([CLAUDE, "-p"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW)
    if ctrl is not None:
        ctrl["proc"] = proc
    try:
        out, err = proc.communicate(input=prompt, timeout=timeout)
        return out, err, proc.returncode, False
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            out, err = proc.communicate()          # 收屍，避免殘留行程繼續吃額度
        except Exception:
            out, err = "", ""
        return out, err, proc.returncode, True
    finally:
        if ctrl is not None:
            ctrl["proc"] = None


def _preflight_auth(ctrl):
    """開跑前快速確認 claude -p 能認證（auth status 會謊報，只有真打一槍才準）。
       回 (ok, why)；why: ""／AUTH／NOCLAUDE。逾時或其他錯誤一律放行(ok=True)，交給正式階段再判，避免誤擋。"""
    try:
        out, err, rc, timed = _run_claude_once("只回覆 OK 兩個字。", ctrl, timeout=120)
    except FileNotFoundError:
        return False, "NOCLAUDE"
    except Exception:
        return True, ""
    if timed:
        return True, ""
    if _looks_auth_error(out, err):
        return False, "AUTH"
    return True, ""


# 長片門檻：逐字稿超過此字數就「分章節多次寫入」，避免單次 claude -p 輸出被截斷
CHUNK_THRESHOLD_CHARS = 24000
CHUNK_BODY_CHARS = 12000          # 每塊正文約對應的逐字稿字數
CHUNK_MAX = 24                    # 上限塊數（放寬以容納超長片如 4 小時課程，避免合併出過大塊而截斷；短片自然切不到這麼多）


def _fmt_t(sec):
    sec = max(0, int(sec or 0))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _segs_to_text(segs):
    return "\n".join(f"[{_fmt_t(s.get('t'))}] {s.get('text', '')}" for s in (segs or []))


def _segments_from_txt(ttxt):
    """transcript.json 沒有可用 segments 時，從 transcript.txt 的 [時間碼] 行還原 pseudo-segments，讓長片仍能分塊。"""
    segs = []
    for line in (ttxt or "").splitlines():
        m = re.match(r"^\s*\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.*)$", line)
        if not m:
            continue
        a, b, c, txt = m.groups()
        t = (int(a) * 3600 + int(b) * 60 + int(c)) if c else (int(a) * 60 + int(b))
        if txt.strip():
            segs.append({"t": t, "text": txt.strip()})
    return segs


# 佔位搪塞語黑名單（真實掉鏈案例＋業界 IF03 缺陷型態）：生成端 prompt 禁用＋驗證端偵測，雙保險
_PLACEHOLDERS = ("見正文", "省略重貼", "以下省略", "（後略）", "(後略)", "內容中斷", "此處中斷",
                 "未在本片段範圍", "本段在此處結束", "省略不貼", "內容相同，省略", "其餘同上",
                 "篇幅所限", "餘略", "【略】", "[略]")


def _find_placeholders(text):
    return [p for p in _PLACEHOLDERS if p in (text or "")]


def _chapter_outline(chapters):
    """章節清單 → 全域大綱字串（給每塊 prompt 當覆蓋契約）。"""
    return " / ".join(f"{_fmt_t(c.get('start'))} {str(c.get('title', ''))[:40]}"
                      for c in (chapters or []) if c.get("title"))


def _chunk_range(segs):
    """一塊 segments 的起迄時間（顯示用）。"""
    ts = [s.get("t") or 0 for s in segs if s.get("text")]
    return (_fmt_t(min(ts)), _fmt_t(max(ts))) if ts else ("", "")


def _split_by_chapters(chapters, segments, max_chars, max_chunks=CHUNK_MAX):
    """章節對齊切塊（結構邊界優先，實證勝等字數切塊 87% vs 13%）：
       章節邊界＝硬切點，塊內按字數上限打包相鄰章節；單章過大才在章內按字數細切；
       無章節（<2）或無 segments 回 []（由呼叫端回退等字數）。"""
    chs = [c for c in (chapters or []) if c.get("title") and c.get("start") is not None]
    segs = [s for s in (segments or []) if s.get("text")]
    if len(chs) < 2 or not segs:
        return []
    bounds = [float(c.get("start") or 0) for c in chs]
    groups = [[] for _ in chs]                      # 依章節分組（切點永遠落在章節邊界）
    gi = 0
    for s in segs:
        t = float(s.get("t") or 0)
        while gi + 1 < len(bounds) and t >= bounds[gi + 1]:
            gi += 1
        groups[gi].append(s)
    chunks, buf, bufn = [], [], 0
    for g in groups:
        if not g:
            continue
        n = sum(len(s.get("text", "")) for s in g)
        if n > max_chars * 1.5:                     # 超大單章：先封緩衝，章內再按字數細切
            if buf:
                chunks.append(buf)
                buf, bufn = [], 0
            chunks.extend(_split_segments(g, max_chars, max_chunks))
        elif buf and bufn + n > max_chars:          # 裝不下：封包，此塊到上一章節為止
            chunks.append(buf)
            buf, bufn = list(g), n
        else:
            buf.extend(g)
            bufn += n
    if buf:
        chunks.append(buf)
    while len(chunks) > max_chunks:                 # 塊數超限：合併相鄰最小兩塊（仍不破章節邊界）
        sizes = [sum(len(s.get("text", "")) for s in c) for c in chunks]
        i = min(range(len(chunks) - 1), key=lambda k: sizes[k] + sizes[k + 1])
        chunks[i:i + 2] = [chunks[i] + chunks[i + 1]]
    return chunks


def _split_segments(segments, max_chars, max_chunks=CHUNK_MAX):
    """依累計字數切塊（不切斷單一 segment）；塊數超過 max_chunks 則加大每塊重切。"""
    segs = [s for s in (segments or []) if s.get("text")]
    if not segs:
        return []
    chunks = []
    for _ in range(12):                          # 保底逃逸：避免病態輸入卡死（理論上會收斂到 1 塊）
        chunks, cur, cnt = [], [], 0
        for s in segs:
            t = len(s.get("text", ""))
            if cur and cnt + t > max_chars:
                chunks.append(cur)
                cur, cnt = [], 0
            cur.append(s)
            cnt += t
        if cur:
            chunks.append(cur)
        if len(chunks) <= max_chunks:
            return chunks
        max_chars = int(max_chars * 1.6)
    return chunks                                 # 逾期保底：寧可超過 max_chunks 也不卡死


def _validate_body(a):
    if len(a) < 150:
        return "EMPTY"
    return None if "##" in a else "INCOMPLETE"


def _make_body_validator(chunk_chars):
    """每塊正文的確定性 QA 門（第一層 lint，毫秒級零成本）：結構／佔位／時間碼／份量樓地板。"""
    floor = max(150, int(chunk_chars * 0.10))       # 寧長毋短：低於該塊逐字稿 10% 視為偷懶摘要

    def validate(a):
        if len(a) < 150:
            return "EMPTY"                          # EMPTY 須最先（_attempt_write 靠它判 auth）
        if "##" not in a:
            return "INCOMPLETE"
        if _find_placeholders(a):
            return "PLACEHOLDER"
        if not re.search(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", a):
            return "NOTIME"
        if len(a) < floor:
            return "SHORT"
        return None
    return validate


def _validate_tail(a):
    return None if (len(a) >= 80 and ("金句" in a or "自我檢核" in a)) else "EMPTY"


_DIAG = {   # 問題代碼 → 給重寫 prompt 的機器可讀診斷（帶診斷的定向重寫，實證勝籠統重試）
    "EMPTY": "輸出過短或無效",
    "INCOMPLETE": "缺少必備結構（章節「##」或必備區塊）",
    "PLACEHOLDER": "出現佔位搪塞語（如「見正文／省略／內容中斷」）——必須把內容完整寫出，不得以任何方式略過",
    "NOTIME": "缺少 [時間碼]——每節開頭必須標逐字稿的真實時間碼",
    "SHORT": "字數遠低於此段逐字稿應有的精讀份量——立場是精讀不是摘要，寧長毋短，請把每個論點、例子、數據、步驟都寫進來",
}


def _attempt_write(prompt, validate_fn, ctrl, log=None):
    """跑 claude -p，失敗自動重試一次並在重寫 prompt 附上具體診斷（auth/timeout/cancel/找不到指令 不重試）。
       回 (clean|None, problem, raw, err, rc)；problem: None/EMPTY/INCOMPLETE/PLACEHOLDER/NOTIME/SHORT/AUTH/TIMEOUT/CANCELLED/NOCLAUDE/ERROR:…。"""
    last_raw = last_err = ""
    last_rc = None
    problem = "EMPTY"
    cur_prompt = prompt
    for attempt in (1, 2):
        if ctrl is not None and ctrl["cancel"].is_set():
            return None, "CANCELLED", last_raw, last_err, last_rc
        try:
            raw, err, rc, timed_out = _run_claude_once(cur_prompt, ctrl)
        except FileNotFoundError:
            return None, "NOCLAUDE", last_raw, last_err, last_rc
        except Exception as e:
            return None, f"ERROR:{e}", last_raw, last_err, last_rc
        last_raw, last_err, last_rc = raw or "", err or "", rc
        if ctrl is not None and ctrl["cancel"].is_set():
            return None, "CANCELLED", last_raw, last_err, last_rc
        if timed_out:
            return None, "TIMEOUT", last_raw, last_err, last_rc
        cand = _strip_and_extract(raw)
        problem = validate_fn(cand)
        if problem is None:
            return cand, None, last_raw, last_err, last_rc
        if problem == "EMPTY" and _looks_auth_error(raw, err):  # 僅「空/錯誤輸出」判認證，避免半成品含「401」字樣被誤判
            return None, "AUTH", last_raw, last_err, last_rc
        if attempt < 2:
            diag = _DIAG.get(problem, str(problem))
            cur_prompt = prompt + f"\n\n【重要】你上一次的輸出不合格：{diag}。請遵守全部鐵則、完整重寫。"
            if log:
                log(f"  第 {attempt} 次輸出不合格（{problem}），帶診斷重寫一次…")
    return None, problem, last_raw, last_err, last_rc


def _fail_log(out, problem, raw, err, rc, log, ctrl):
    """統一失敗收斂：落地存證 + 明確可行動訊息（別再默默吞掉真因）。"""
    try:
        (out / "_write_error.log").write_text(
            f"problem={problem} returncode={rc}\n\n[stdout]\n{raw}\n\n[stderr]\n{err}", encoding="utf-8")
    except Exception:
        pass
    if problem == "CANCELLED":
        return
    if problem == "AUTH":
        if ctrl is not None:
            ctrl["auth_failed"] = True
        log("✗ 撰寫失敗：claude -p 認證失敗（401）。請在一般終端機執行 `claude auth login` 重新登入後再試。")
    elif problem == "TIMEOUT":
        log("✗ 撰寫失敗：claude -p 逾時（>40 分）已中止子行程。長片請改用桌面互動式或稍後再試。")
    elif problem == "NOCLAUDE":
        log("✗ 撰寫失敗：找不到 claude 指令，請確認 Claude Code 已安裝且在 PATH。")
    elif problem == "INCOMPLETE":
        log("✗ 撰寫失敗：兩次輸出都缺少必備內容（詳見資料夾內 _write_error.log）。")
    elif problem in ("PLACEHOLDER", "SHORT", "NOTIME"):
        why = {"PLACEHOLDER": "佔位搪塞語", "SHORT": "精讀份量不足", "NOTIME": "缺時間碼"}[problem]
        log(f"✗ 撰寫失敗：兩次輸出都未通過品質門（{why}），詳見 _write_error.log。")
    elif isinstance(problem, str) and problem.startswith("ERROR:"):
        log(f"✗ 撰寫失敗：{problem[6:]}")
    else:
        log("✗ Claude 未回傳有效內容（詳見資料夾內 _write_error.log）。")
    combined = (raw + "\n" + err).strip()
    if combined:
        log("  " + combined.replace("\n", " ")[:200])


def _write_quality_report(out, article, chunks, ttxt, mode, log):
    """產後完整性審計（確定性、零 LLM）：佔位／長度比／各塊時間覆蓋／時間碼單調性 → _quality_report.txt。
       只回報不擋交付；審計本身出錯絕不能中斷流程。"""
    try:
        lines, warns = [], 0
        ph = _find_placeholders(article)
        if ph:
            warns += 1
            lines.append(f"[WARN] 佔位搪塞語：{'、'.join(ph)}")
        else:
            lines.append("[OK] 無佔位搪塞語")
        if mode != "快覽" and ttxt:
            ratio = len(article) / len(ttxt)
            ok = ratio >= 0.35
            lines.append(f"[{'OK' if ok else 'WARN'}] 文章/逐字稿長度比 {ratio:.2f}（樓地板 0.35）")
            if not ok:
                warns += 1
        ts = [(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m.group(3)
              else (int(m.group(1)) * 60 + int(m.group(2)))
              for m in re.finditer(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]", article)]
        if len(ts) >= 2:
            inv = sum(1 for a, b in zip(ts, ts[1:]) if b < a - 120)   # 容忍 2 分鐘內回指
            frac = inv / (len(ts) - 1)
            ok = frac <= 0.15
            lines.append(f"[{'OK' if ok else 'WARN'}] 時間碼單調性：{len(ts)} 個、倒退比 {frac:.0%}（容忍 15%）")
            if not ok:
                warns += 1
        for i, seg in enumerate(chunks or [], 1):    # 時間碼覆蓋審計：每塊時間範圍都要有對應時間碼
            tt = [s.get("t") or 0 for s in seg if s.get("text")]
            if not tt:
                continue
            t0, t1 = min(tt), max(tt)
            hit = any(t0 - 60 <= x <= t1 + 60 for x in ts)
            lines.append(f"[{'OK' if hit else 'WARN'}] 第 {i} 塊（{_fmt_t(t0)}–{_fmt_t(t1)}）{'有' if hit else '無'}對應時間碼")
            if not hit:
                warns += 1
        head = ("完整性審計：" + ("全部通過" if warns == 0 else f"{warns} 項警告") + "\n" + "-" * 40 + "\n")
        (out / "_quality_report.txt").write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
        if warns:
            log(f"  ⚠ 完整性審計：{warns} 項警告（詳見 _quality_report.txt）")
        else:
            log("  ✓ 完整性審計通過")
    except Exception:
        pass


def _finish_article(out, article, ttxt, mode, log, chunks=None):
    """共用收尾：截斷警告 + 寫 article.md + 完整性審計 + 渲染 + 衍生格式 + render/write 分離回報。"""
    if mode != "快覽" and len(ttxt) > 0 and len(article) < 0.35 * len(ttxt):
        log(f"  ⚠ 注意：文章長度（{len(article):,}）明顯短於逐字稿（{len(ttxt):,}），疑似被截斷或過簡，請開檔檢查是否完整。")
    try:
        (out / "article.md").write_text(article, encoding="utf-8")
    except Exception as e:
        try:
            (out / "_write_error.log").write_text(f"problem=WRITE_MD\n{e}", encoding="utf-8")
        except Exception:
            pass
        log(f"✗ 寫入 article.md 失敗：{e}")
        return False
    _write_quality_report(out, article, chunks, ttxt, mode, log)
    log(f"  已產出文章（{len(article):,} 字），渲染中…")
    r = subprocess.run([PY, str(RENDER), "--md", str(out / "article.md"),
                        "--json", str(out / "transcript.json"), "--out", str(out / "article.html")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW)
    if not (out / "article.html").exists():
        # 文章已寫成 article.md，純粹渲染掛了 → 別誤報成「撰寫未完成」害使用者以為白做工
        try:
            (out / "_render_error.log").write_text(
                f"returncode={r.returncode}\n\n[stdout]\n{r.stdout or ''}\n\n[stderr]\n{r.stderr or ''}",
                encoding="utf-8")
        except Exception:
            pass
        emsg = ((r.stderr or "") or (r.stdout or "")).strip().replace("\n", " ")[:200]
        log(f"✗ 文章已寫成 article.md，但渲染 HTML 失敗：{emsg}（詳見 _render_error.log）")
        return False
    if DERIVE.exists():                              # 衍生格式（精華卡/心智圖/自測卡）：零 LLM、失敗不擋交付
        try:
            subprocess.run([PY, str(DERIVE), str(out)], capture_output=True, timeout=120,
                           creationflags=NO_WINDOW)
        except Exception:
            pass
    return True


def _with_heartbeat(log, fn):
    """跑 fn() 期間每 15 秒回報一次仍在撰寫，結束自動停止。"""
    stop = threading.Event()

    def beat():
        t = 0
        while not stop.wait(15):
            t += 15
            log(f"  …仍在撰寫（已 {t} 秒）")
    threading.Thread(target=beat, daemon=True).start()
    try:
        return fn()
    finally:
        stop.set()


def _prompt_frame(meta, full_ttxt, mode, is_asr):
    asr = "（逐字稿由語音辨識產生，可能有錯字，合理修正但不改原意）\n" if is_asr else ""
    return (
        "你是把長影片逐字稿精讀成繁體中文長文的編輯。這一步【只輸出文章的開頭框架】，不要寫章節正文。\n"
        "嚴格只輸出以下三段，第一個字元就是「#」：\n"
        "# 標題（用下方提供的標題）\n"
        "## 💡 重點洞察  → 3–6 條一句話洞察，每條「- 」，可帶 [時間碼]\n"
        "## ⚡ 可應用 / 帶得走的行動  → 3–8 條具體可執行行動，每條「- 」，附 [時間碼]\n"
        "最後輸出一行「---」。不要章節正文、不要金句、不要解說、不要 ``` 圍欄。\n"
        + asr + f"標題：{meta.get('title', '')}\n頻道／節目：{meta.get('channel', '')}\n\n"
        "==== 全片逐字稿（供你綜觀全局）====\n" + full_ttxt
    )


def _prompt_body(meta, chunk_ttxt, mode, is_asr, idx, total, outline="", rng=("", ""), prev=""):
    asr = "（語音辨識稿，可能有錯字，合理修正不改原意）\n" if is_asr else ""
    ctx = ""
    if outline:
        ctx += f"全片章節大綱（覆蓋契約，供你定位本段在全文的位置）：{outline}\n"
    if rng and rng[0]:
        ctx += f"本段時間範圍：{rng[0]} – {rng[1]}（你的正文時間碼都應落在此範圍內）\n"
    if prev:
        ctx += f"（銜接參考）上一段正文的結尾：「…{prev}」——請自然銜接、不要重複已寫過的內容。\n"
    return (
        f"你正在精讀一支長影片的第 {idx}/{total} 段逐字稿，產出這一段對應的【章節正文】。\n"
        "鐵則：①忠實不杜撰、保留所有細節（步驟／數字／價格／工具／話術）、去口水詞重組成通順書面段落、繁體中文。"
        "②【嚴禁佔位搪塞】絕不可出現「見正文」「省略」「後續不在範圍」「內容中斷」「內容相同」等字樣——你負責的這段逐字稿就是全部素材，一律寫完整、不截斷。"
        "③【嚴禁杜撰人名】講者與人名一律照逐字稿；沒把握的名字寫「講者」，不可自創。\n"
        + ctx +
        "只輸出這一段的章節正文：用「## 章節標題 [時間碼]」分節（一節一主題），每節開頭標時間碼（取自逐字稿真實時間，超過 1 小時用 h:mm:ss，否則 mm:ss，同一篇風格一致），"
        "重要原話用「> 引言」，流程／比較可用條列或表格，可用 > [!key] / [!note] / [!warn] 強調框。\n"
        "【不要】寫文章大標題(#)、不要重點洞察／帶得走／金句／自我檢核、不要「---」、不要前言結語、不要 ``` 圍欄；"
        "第一個字元就是二級標題「##」。\n"
        f"深度：{mode}。\n" + asr +
        f"標題：{meta.get('title', '')}\n\n==== 第 {idx}/{total} 段逐字稿 ====\n" + chunk_ttxt
    )


def _prompt_tail(meta, full_ttxt, mode, is_asr):
    return (
        "你是長影片精讀編輯。這一步【只輸出文章結尾的綜整三節】，根據全片內容撰寫：\n"
        "## ❝ 金句  → 3–5 句最有力的原話，每句一行「> 引言」，附 [時間碼]\n"
        "## 🧠 自我檢核  → 3–6 題，每行『- 問題？｜答案』（全形｜分隔）\n"
        "## 名詞解釋 / 關鍵結論  → 視內容列幾條重要名詞或結論\n"
        "只輸出這三節（第一個字元是「#」），不要重寫正文、不要文章大標題、不要解說、不要 ``` 圍欄。\n\n"
        f"標題：{meta.get('title', '')}\n\n==== 全片逐字稿 ====\n" + full_ttxt
    )


def _write_single(out, meta, ttxt, mode, is_asr, log, ctrl):
    log("Claude 正在撰寫精讀文章中…")
    prompt = build_writer_prompt(meta, ttxt, mode, is_asr)
    article, problem, raw, err, rc = _with_heartbeat(
        log, lambda: _attempt_write(prompt, _validate_article, ctrl, log))
    if article is None:
        if problem != "CANCELLED":
            _fail_log(out, problem, raw, err, rc, log, ctrl)
        return False
    return _finish_article(out, article, ttxt, mode, log)


def _write_long_article(out, meta, chunks, ttxt, mode, is_asr, log, ctrl, chapters=None):
    n = len(chunks)
    outline = _chapter_outline(chapters)
    log(f"長片：分 {n} 段＋框架＋結尾多次撰寫（避免單次輸出截斷）…")

    def gen():
        # 1) 框架（全片）：標題 + 重點洞察 + 帶得走行動
        fr, p, raw, err, rc = _attempt_write(_prompt_frame(meta, ttxt, mode, is_asr), _validate_article, ctrl, log)
        if fr is None:
            return None, ("框架", p, raw, err, rc)
        # 2) 正文（逐塊；任一塊失敗就整體收斂，不產出殘缺文章）
        bodies = []
        for i, seg in enumerate(chunks, 1):
            if ctrl is not None and ctrl["cancel"].is_set():
                return None, ("取消", "CANCELLED", "", "", None)
            log(f"  撰寫正文 {i}/{n} …")
            chunk_chars = sum(len(s.get("text", "")) for s in seg)
            prev_tail = bodies[-1][-300:] if bodies else ""      # 前文縫合：Map 的平行度＋Refine 的連貫性
            b, p, raw, err, rc = _attempt_write(
                _prompt_body(meta, _segs_to_text(seg), mode, is_asr, i, n,
                             outline=outline, rng=_chunk_range(seg), prev=prev_tail),
                _make_body_validator(chunk_chars), ctrl, log)
            if b is None:
                return None, (f"正文第 {i} 段", p, raw, err, rc)
            bodies.append(b.strip())
        # 3) 結尾（全片）：金句 + 自我檢核 + 名詞解釋（非必要，失敗就略過不擋全文）
        tl, _, _, _, _ = _attempt_write(_prompt_tail(meta, ttxt, mode, is_asr), _validate_tail, ctrl, log)
        if not tl:
            log("  （結尾綜整：金句/自我檢核未產出，已略過，不影響正文完整）")
        head = fr.rstrip()
        if not head.endswith("---"):
            head += "\n\n---"
        art = head + "\n\n" + "\n\n".join(bodies)
        if tl:
            art += "\n\n" + tl.strip()
        return art, None

    article, fail = _with_heartbeat(log, gen)
    if article is None:
        where, problem, raw, err, rc = fail
        if problem != "CANCELLED":
            log(f"✗ 長片撰寫在「{where}」失敗。")
            _fail_log(out, problem, raw, err, rc, log, ctrl)
        return False
    return _finish_article(out, article, ttxt, mode, log, chunks=chunks)


def write_article_via_claude(out_dir, mode, log, ctrl=None):
    out = Path(out_dir)
    try:
        data = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    except Exception as e:
        log(f"✗ 讀逐字稿失敗：{e}")
        return False
    meta = data.get("meta", {})
    is_asr = (data.get("track", {}) or {}).get("source") == "whisper"
    try:
        ttxt = (out / "transcript.txt").read_text(encoding="utf-8")
    except Exception:
        ttxt = _segs_to_text(data.get("segments", []))
    # 路由：短片單次（已驗證路徑）；長片分塊（避免單次輸出截斷）；快覽因輸出短不分塊
    if mode != "快覽" and len(ttxt) > CHUNK_THRESHOLD_CHARS:
        segments = data.get("segments", [])
        chapters = data.get("chapters") or []
        chunks = _split_by_chapters(chapters, segments, CHUNK_BODY_CHARS)   # 章節對齊優先：結構邊界硬切點
        how = "章節對齊"
        if len(chunks) < 2:                       # 無章節 → 等字數切
            chunks = _split_segments(segments, CHUNK_BODY_CHARS)
            how = "等字數"
        if len(chunks) < 2:                       # transcript.json 無可用 segments → 從 txt 還原時間碼再切
            chunks = _split_segments(_segments_from_txt(ttxt), CHUNK_BODY_CHARS)
            how = "txt還原"
        if len(chunks) >= 2:
            log(f"  切塊方式：{how}（{len(chunks)} 塊）")
            return _write_long_article(out, meta, chunks, ttxt, mode, is_asr, log, ctrl, chapters=chapters)
        log("  ⚠ 長片但無法分塊（逐字稿缺時間碼），改單次撰寫、可能被截斷，請開檔檢查完整性。")
    return _write_single(out, meta, ttxt, mode, is_asr, log, ctrl)


REASON_MSG = {
    "NO_SUBTITLES": "無字幕", "SUBTITLE_EMPTY": "字幕無法解析",
    "NEEDS_LOGIN": "需登入（X/受限）", "NEEDS_WHISPER": "缺語音辨識套件",
    "AUDIO_FAILED": "音訊下載失敗", "ASR_EMPTY": "無語音可辨識",
    "VIDEO_UNAVAILABLE": "影片無法播放", "PRIVATE": "私人影片",
    "MEMBERS_ONLY": "會員限定", "AGE_RESTRICTED": "年齡限制需登入",
    "SPOTIFY_DRM": "Spotify不支援(改貼Apple/RSS)", "FIRSTORY_PAGE": "Firstory單集頁(改貼Apple/RSS)",
    "UNSUPPORTED": "連結不支援(貼單集/RSS)", "NO_EPISODES": "RSS內無單集",
    "CANCELLED": "已取消", "UNKNOWN": "未知原因(請確認網址或重試)",
}
MODELS = {"快": "base", "標準": "small", "高": "medium"}


def parse_urls(text):
    out, seen = [], set()
    for line in (text or "").replace(",", "\n").split("\n"):
        u = line.strip()
        if re.match(r"https?://", u) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def short(s, n=48):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# GUI（customtkinter 專業版・支援批次）
# ---------------------------------------------------------------------------
def start_gui():
    import customtkinter as ctk

    cats, last_cat = load_cats()
    try:
        ctk.set_default_color_theme(str(THEME))
    except Exception:
        pass
    ctk.set_appearance_mode("dark")
    try:
        ctk.set_widget_scaling(1.06)
    except Exception:
        pass

    root = ctk.CTk()
    root.title("影片轉文章")
    W, H = 820, 860
    root.minsize(740, 780)
    root.update_idletasks()
    x = (root.winfo_screenwidth() - W) // 2
    y = max(0, (root.winfo_screenheight() - H) // 2 - 20)
    root.geometry(f"{W}x{H}+{x}+{y}")
    try:
        root.iconbitmap(str(SKILL_DIR / "app.ico"))
    except Exception:
        pass

    FAM = "Microsoft JhengHei UI"
    F = {
        "h1": ctk.CTkFont(FAM, 26, "bold"), "sub": ctk.CTkFont(FAM, 14),
        "lab": ctk.CTkFont(FAM, 14, "bold"), "body": ctk.CTkFont(FAM, 14),
        "small": ctk.CTkFont(FAM, 12), "btn": ctk.CTkFont(FAM, 15, "bold"),
        "row": ctk.CTkFont(FAM, 13), "rowb": ctk.CTkFont(FAM, 13, "bold"),
        "step": ctk.CTkFont(FAM, 16, "bold"), "url": ctk.CTkFont("Consolas", 13),
    }

    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(4, weight=1)

    head = ctk.CTkFrame(root, fg_color="transparent")
    head.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 4))
    head.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(head, text="🎬  影片轉文章", font=F["h1"], text_color=TXT_HI).grid(row=0, column=0, sticky="w")
    ctk.CTkLabel(head, text="貼上一支或多支網址，一鍵批次變成可閱讀的精讀文章 · YouTube / Podcast / X / Vimeo",
                 font=F["sub"], text_color=GOLD).grid(row=1, column=0, sticky="w", pady=(2, 0))

    # ---- 輸入卡片 ----
    card = ctk.CTkFrame(root, fg_color=CARD, border_color=CARD_BORDER, border_width=1, corner_radius=14)
    card.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 10))
    card.grid_columnconfigure(0, weight=1)
    pad = {"padx": 20}

    urlhdr = ctk.CTkFrame(card, fg_color="transparent")
    urlhdr.grid(row=0, column=0, sticky="ew", pady=(14, 4), **pad)
    urlhdr.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(urlhdr, text="影片／Podcast 網址", font=F["lab"], text_color=TXT_HI).grid(row=0, column=0, sticky="w")
    cnt_lab = ctk.CTkLabel(urlhdr, text="一行一個，可貼多支批次（YouTube／Apple Podcasts／SoundCloud／Firstory／SoundOn／RSS）", font=F["small"], text_color=TXT_LO)
    cnt_lab.grid(row=0, column=1, sticky="e")
    url_box = ctk.CTkTextbox(card, font=F["url"], height=92, corner_radius=10, wrap="none")
    url_box.grid(row=1, column=0, sticky="ew", pady=(0, 12), **pad)

    opt = ctk.CTkFrame(card, fg_color="transparent")
    opt.grid(row=2, column=0, sticky="ew", pady=(0, 6), **pad)
    opt.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(opt, text="精讀深度", font=F["lab"], text_color=TXT_LO).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 12))
    depth_seg = ctk.CTkSegmentedButton(opt, values=["逐節精讀", "快覽", "逐字精修"], font=F["btn"], height=34)
    depth_seg.set("逐節精讀")
    depth_seg.grid(row=0, column=1, sticky="ew", pady=6)
    ctk.CTkLabel(opt, text="無字幕辨識品質", font=F["lab"], text_color=TXT_LO).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 12))
    qrow = ctk.CTkFrame(opt, fg_color="transparent")
    qrow.grid(row=1, column=1, sticky="ew", pady=6)
    qrow.grid_columnconfigure(0, weight=1)
    quality_seg = ctk.CTkSegmentedButton(qrow, values=["快", "標準", "高"], font=F["btn"], height=34)
    quality_seg.set("標準")
    quality_seg.grid(row=0, column=0, sticky="ew")
    ctk.CTkLabel(qrow, text="有 GPU 自動用最高品質", font=F["small"], text_color=TXT_LO).grid(row=0, column=1, padx=(10, 0))
    ctk.CTkLabel(opt, text="知識分類", font=F["lab"], text_color=TXT_LO).grid(row=2, column=0, sticky="w", pady=(6, 12), padx=(0, 12))
    crow = ctk.CTkFrame(opt, fg_color="transparent")
    crow.grid(row=2, column=1, sticky="ew", pady=(6, 12))
    crow.grid_columnconfigure(0, weight=1)
    cat_combo = ctk.CTkComboBox(crow, font=F["body"], height=38, values=cats, dropdown_font=F["body"])
    cat_combo.set(last_cat or cats[0])
    cat_combo.grid(row=0, column=0, sticky="ew")
    lang_entry = ctk.CTkEntry(crow, font=F["body"], height=38, width=120, placeholder_text="語言(選填)")
    lang_entry.grid(row=0, column=1, padx=(10, 0))

    btnrow = ctk.CTkFrame(root, fg_color="transparent")
    btnrow.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 10))
    btnrow.grid_columnconfigure(0, weight=1)
    start_btn = ctk.CTkButton(btnrow, text="開始作業  ▶", font=F["btn"], height=46, corner_radius=12,
                              fg_color=GOLD, hover_color=GOLD_HOVER, text_color=DEEP)
    start_btn.grid(row=0, column=0, sticky="ew")
    cancel_btn = ctk.CTkButton(btnrow, text="✕ 取消", font=F["btn"], height=46, corner_radius=12, width=120,
                               fg_color="transparent", hover_color=CARD, border_width=1, border_color=RED,
                               text_color=RED, state="disabled")
    cancel_btn.grid(row=0, column=1, padx=(10, 0))

    prog_card = ctk.CTkFrame(root, fg_color=CARD, border_color=CARD_BORDER, border_width=1, corner_radius=14)
    prog_card.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 10))
    prog_card.grid_columnconfigure(0, weight=1)
    step_lab = ctk.CTkLabel(prog_card, text="就緒", font=F["step"], text_color=TXT_HI, anchor="w")
    step_lab.grid(row=0, column=0, sticky="ew", padx=18, pady=(13, 7))
    bar = ctk.CTkProgressBar(prog_card, height=12, corner_radius=1000, progress_color=GOLD)
    bar.set(0)
    bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
    sub_lab = ctk.CTkLabel(prog_card, text="貼上網址後按「開始作業」", font=F["small"], text_color=TXT_LO, anchor="w")
    sub_lab.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 13))

    # ---- 佇列清單（每支影片一列）----
    qframe = ctk.CTkScrollableFrame(root, fg_color=DEEP, corner_radius=12, label_text="處理佇列",
                                    label_font=F["lab"], label_text_color=TXT_LO)
    qframe.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 10))
    qframe.grid_columnconfigure(0, weight=1)

    act = ctk.CTkFrame(root, fg_color="transparent")
    act.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 8))
    act.grid_columnconfigure(4, weight=1)
    open_btn = ctk.CTkButton(act, text="開啟文章", font=F["btn"], height=40, corner_radius=10,
                             fg_color=NAVY, hover_color=NAVY_HOVER, state="disabled", width=104)
    open_btn.grid(row=0, column=0, padx=(0, 8))
    folder_btn = ctk.CTkButton(act, text="📂 資料夾", font=F["small"], height=40, corner_radius=10,
                               fg_color="transparent", hover_color=CARD, border_width=1, border_color=CARD_BORDER,
                               text_color=TXT_LO, state="disabled", width=92)
    folder_btn.grid(row=0, column=1, padx=(0, 8))
    export_btn = ctk.CTkButton(act, text="↧ 匯出檔", font=F["small"], height=40, corner_radius=10,
                               fg_color="transparent", hover_color=CARD, border_width=1, border_color=CARD_BORDER,
                               text_color=TXT_LO, state="disabled", width=92)
    export_btn.grid(row=0, column=2, padx=(0, 8))
    obsidian_btn = ctk.CTkButton(act, text="📥 送到 Obsidian", font=F["small"], height=40, corner_radius=10,
                                 fg_color="transparent", hover_color=CARD, border_width=1, border_color=CARD_BORDER,
                                 text_color=TXT_LO, state="disabled", width=140)
    obsidian_btn.grid(row=0, column=3, padx=(0, 8))
    relogin_btn = ctk.CTkButton(act, text="🔑 修復登入", font=F["small"], height=40, corner_radius=10,
                                fg_color="transparent", hover_color=CARD, border_width=1, border_color=GOLD,
                                text_color=GOLD, width=104)
    relogin_btn.grid(row=0, column=5, padx=(0, 8))
    index_btn = ctk.CTkButton(act, text="📚 知識總覽", font=F["small"], height=40, corner_radius=10,
                              fg_color=NAVY, hover_color=NAVY_HOVER, width=112)
    index_btn.grid(row=0, column=6, sticky="e")

    status = ctk.CTkLabel(root, text="就緒", font=F["small"], text_color=TXT_LO, anchor="w",
                          fg_color=DEEP, height=26)
    status.grid(row=6, column=0, sticky="ew")

    q = queue.Queue()
    st = {"busy": False, "active": -1, "last_article": None, "last_dir": None}
    ctrl = {"cancel": threading.Event(), "proc": None}   # 取消旗標＋目前子行程
    crawl = {"on": False}
    rows = []  # 每列 dict: frame/dot/title/stat

    # ---- URL 數量即時提示 + 按鈕文案 ----
    def recount(_=None):
        n = len(parse_urls(url_box.get("1.0", "end")))
        cnt_lab.configure(text=(f"已偵測 {n} 支網址" if n else "一行一個，可貼多支批次"))
        if not st["busy"]:
            start_btn.configure(text=("開始作業  ▶" if n <= 1 else f"批次處理 {n} 支  ▶"))
    url_box.bind("<KeyRelease>", recount)

    # ---- 佇列列 ----
    def build_rows(urls):
        for r in rows:
            r["frame"].destroy()
        rows.clear()
        for i, u in enumerate(urls):
            fr = ctk.CTkFrame(qframe, fg_color=FIELD, corner_radius=8)
            fr.grid(row=i, column=0, sticky="ew", pady=4, padx=2)
            fr.grid_columnconfigure(1, weight=1)
            dot = ctk.CTkLabel(fr, text="●", font=F["rowb"], text_color="#5b6b7f", width=18)
            dot.grid(row=0, column=0, padx=(12, 8), pady=9)
            title = ctk.CTkLabel(fr, text=short(u, 52), font=F["row"], text_color=TXT_HI, anchor="w")
            title.grid(row=0, column=1, sticky="ew", pady=9)
            stat = ctk.CTkLabel(fr, text="待處理", font=F["row"], text_color=TXT_LO, anchor="e")
            stat.grid(row=0, column=2, padx=(8, 14), pady=9)
            rows.append({"frame": fr, "dot": dot, "title": title, "stat": stat})

    def set_row(i, dot=None, title=None, stat=None, dotc=None, statc=None):
        if 0 <= i < len(rows):
            r = rows[i]
            if dot is not None:
                r["dot"].configure(text=dot)
            if dotc is not None:
                r["dot"].configure(text_color=dotc)
            if title is not None:
                r["title"].configure(text=short(title, 52))
            if stat is not None:
                r["stat"].configure(text=stat)
            if statc is not None:
                r["stat"].configure(text_color=statc)

    def set_bar(v):
        if v > bar.get():
            bar.set(min(1.0, v))

    def crawl_step():
        if crawl["on"]:
            v = bar.get()
            if v < 0.92:
                bar.set(min(0.92, v + 0.006))
            root.after(450, crawl_step)

    def enter_article(i):
        if not crawl["on"]:
            crawl["on"] = True
            set_bar(0.60)
            set_row(i, stat="撰寫中…")
            root.after(450, crawl_step)

    def handle_line(i, raw):
        if i != st["active"]:
            return
        if raw.lstrip().startswith("✗"):          # 失敗訊息：直接顯示真因，別讓它消失
            sub_lab.configure(text=raw.strip()[:90], text_color=RED)
            return
        m = re.search(r"@@PCT@@(\d+)", raw)
        if m:
            p = int(m.group(1))
            set_bar(0.15 + p / 100.0 * 0.42)
            step_lab.configure(text=f"{batchtag()}語音辨識中…  {p}%")
            set_row(i, stat=f"辨識 {p}%")
            return
        if "GPU 加速就緒" in raw:
            step_lab.configure(text=f"{batchtag()}啟用 GPU 加速…")
            sub_lab.configure(text="GPU 辨識模型：large-v3-turbo")
        elif "載入 CPU 模型" in raw:
            sub_lab.configure(text="CPU 辨識中（無 GPU 或已退回）")
        elif raw.strip().startswith("音訊：") or "音訊：" in raw:
            sub_lab.configure(text=raw.split("音訊：", 1)[-1].strip()[:60])
        elif "[3/4]" in raw or "下載並解析字幕" in raw:
            set_bar(0.22); step_lab.configure(text=f"{batchtag()}下載字幕…"); set_row(i, stat="下載字幕…")
        elif "下載音訊" in raw:
            set_bar(0.16); step_lab.configure(text=f"{batchtag()}下載音訊…"); set_row(i, stat="下載音訊…")
        elif "yt-dlp 下載字幕" in raw:
            step_lab.configure(text=f"{batchtag()}正規下載字幕…")
        elif "Claude 正在撰寫" in raw:
            step_lab.configure(text=f"{batchtag()}Claude 逐節精讀中…")
            enter_article(i)
        elif "仍在撰寫" in raw:
            mm = re.search(r"已 (\d+) 秒", raw)
            if mm:
                sub_lab.configure(text=f"Claude 撰寫中…  已 {mm.group(1)} 秒")
        elif "已產出文章" in raw:
            crawl["on"] = False
            set_bar(0.93); step_lab.configure(text=f"{batchtag()}渲染閱讀版…")

    def batchtag():
        total = len(rows)
        return f"批次 {st['active']+1}/{total} · " if total > 1 else ""

    def drain():
        try:
            while True:
                kind, *pl = q.get_nowait()
                if kind == "log":
                    handle_line(pl[0], pl[1])
                elif kind == "active":
                    i = pl[0]
                    st["active"] = i
                    crawl["on"] = False
                    bar.set(0)
                    set_row(i, dot="●", dotc=GOLD, stat="處理中…")
                    step_lab.configure(text=f"{batchtag()}準備中…", text_color=TXT_HI)
                    sub_lab.configure(text=pl[1])
                elif kind == "rowtitle":
                    set_row(pl[0], title=pl[1])
                elif kind == "itemdone":
                    i, ok, msg = pl
                    crawl["on"] = False
                    if ok:
                        bar.set(1.0)
                        set_row(i, dot="✓", dotc=GREEN, stat=msg, statc=GREEN)
                    else:
                        set_row(i, dot="✗", dotc=RED, stat=msg, statc=RED)
                elif kind == "actions":
                    st["last_article"], st["last_dir"] = pl[0], pl[1]
                    if pl[0]:
                        open_btn.configure(state="normal")
                    if pl[1]:
                        folder_btn.configure(state="normal")
                        export_btn.configure(state="normal")
                        obsidian_btn.configure(state="normal")
                elif kind == "done":
                    finalize(pl[0])
                    return
        except queue.Empty:
            pass
        root.after(80, drain)

    def finalize(summary):
        if st.get("finalized"):                  # 一次性保護：避免重複收尾
            return
        st["finalized"] = True
        crawl["on"] = False
        st["busy"] = False
        bar.set(1.0)
        ok_n, total, failed = summary
        cancelled = ctrl["cancel"].is_set()
        start_btn.configure(state="normal")
        cancel_btn.configure(state="disabled", text="✕ 取消")
        recount()
        if cancelled:
            step_lab.configure(text=f"已取消（已完成 {ok_n}/{total}）", text_color=RED)
            status.configure(text="已取消", text_color=RED)
            sub_lab.configure(text="已完成的部分已歸入知識總覽")
            return
        if ok_n == total:
            step_lab.configure(text=f"全部完成 ✓  {ok_n}/{total}", text_color=GREEN)
            status.configure(text=f"完成 {ok_n}/{total}", text_color=GREEN)
        else:
            step_lab.configure(text=f"完成 {ok_n}/{total}（{len(failed)} 支略過）", text_color=GOLD)
            status.configure(text="完成（部分略過）", text_color=GOLD)
        sub_lab.configure(text="已歸入知識總覽" + ("；失敗：" + "、".join(failed[:4]) if failed else ""))
        if ctrl.get("auth_failed"):
            step_lab.configure(text="claude 未登入 · 已自動開啟登入視窗", text_color=RED)
            status.configure(text="完成瀏覽器登入後，回來重按「開始作業」即可（一次性，登入後就不會再出現）", text_color=RED)
            sub_lab.configure(text="若沒跳出視窗，按右下「🔑 修復登入」，或終端機跑 `claude auth login`", text_color=TXT_LO)
            if not st.get("login_opened"):       # 主動把登入視窗開出來，不必使用者自己找按鈕
                st["login_opened"] = True
                try:
                    do_relogin()
                except Exception:
                    pass                          # 自動開窗失敗不可拖垮 UI；右下按鈕仍可手動
            return
        # 開啟：單支→文章；多支→知識總覽
        if total == 1 and st["last_article"]:
            try:
                os.startfile(st["last_article"])
            except Exception:
                pass
        else:
            idx = BASE / "index.html"
            if idx.exists():
                try:
                    os.startfile(str(idx))
                except Exception:
                    pass

    # ---- worker（逐一處理，失敗略過續跑）----
    def worker(urls, lang, mode, model, category):
        ok_n = 0
        failed = []
        last_article = last_dir = None
        # 開跑前先驗認證：沒登入就別白抓字幕，直接擋下並導向「🔑 修復登入」
        q.put(("active", 0, "檢查登入狀態…"))
        ok_auth, why = _preflight_auth(ctrl)
        if not ok_auth and not ctrl["cancel"].is_set():
            ctrl["auth_failed"] = (why == "AUTH")
            msg = ("✗ claude 未登入：請按右下「🔑 修復登入」（或終端機跑 `claude setup-token` 永久解／`claude auth login`），完成後再按開始。"
                   if why == "AUTH" else
                   "✗ 找不到 claude 指令，請確認 Claude Code 已安裝且在 PATH。")
            q.put(("log", 0, msg))
            for j in range(len(urls)):
                q.put(("itemdone", j, False, "略過（待登入）" if why == "AUTH" else "略過（缺 claude）"))
            q.put(("actions", None, None))
            q.put(("done", (0, len(urls), [short(u, 24) for u in urls])))
            return
        for i, url in enumerate(urls):
            if ctrl["cancel"].is_set():
                break
            q.put(("active", i, f"第 {i+1}/{len(urls)} 支 · 連線中…"))

            def L(s, _i=i):
                q.put(("log", _i, s))
            try:
                info = run_fetch(url, lang, model, BASE / category, L, ctrl)
                if ctrl["cancel"].is_set():
                    q.put(("itemdone", i, False, "已取消"))
                    break
                if not info.get("ok"):
                    failed.append(short(url, 24))
                    q.put(("itemdone", i, False, REASON_MSG.get(info.get("reason"), "失敗")))
                    continue
                out_dir = info["out_dir"]
                last_dir = out_dir
                q.put(("rowtitle", i, info.get("title", url)))
                saved = [c for c in (load_cats()[0]) if c != category]
                save_cats([category] + saved, category)
                run_build_index()
                okw = write_article_via_claude(out_dir, mode, L, ctrl)
                if ctrl["cancel"].is_set():
                    q.put(("itemdone", i, False, "已取消"))
                    break
                if okw:
                    ok_n += 1
                    last_article = os.path.join(out_dir, "article.html")
                    q.put(("itemdone", i, True, "✓ 完成"))
                else:
                    failed.append(short(info.get("title", url), 24))
                    q.put(("itemdone", i, False, "撰寫未完成"))
                    if ctrl.get("auth_failed"):
                        # 認證壞了，後續每支都會 401——快速失敗，別再白抓字幕
                        for j in range(i + 1, len(urls)):
                            q.put(("itemdone", j, False, "略過（待登入）"))
                        break
            except Exception as e:
                failed.append(short(url, 24))
                q.put(("itemdone", i, False, f"例外：{str(e)[:20]}"))
        run_build_index()
        q.put(("actions", last_article, last_dir))
        q.put(("done", (ok_n, len(urls), failed)))

    def on_start():
        if st["busy"]:
            return
        urls = parse_urls(url_box.get("1.0", "end"))
        if not urls:
            step_lab.configure(text="沒有有效網址", text_color=RED)
            sub_lab.configure(text="請一行一個貼上 http 開頭的影片網址")
            status.configure(text="請貼上有效網址", text_color=RED)
            return
        st.update(busy=True, active=-1, last_article=None, last_dir=None)
        ctrl["cancel"].clear()
        ctrl["proc"] = None
        ctrl["auth_failed"] = False
        st["login_opened"] = False
        st["finalized"] = False
        build_rows(urls)
        start_btn.configure(state="disabled", text="處理中…")
        cancel_btn.configure(state="normal", text="✕ 取消")
        open_btn.configure(state="disabled")
        folder_btn.configure(state="disabled")
        export_btn.configure(state="disabled")
        obsidian_btn.configure(state="disabled")
        bar.set(0)
        step_lab.configure(text=("準備中…" if len(urls) == 1 else f"批次 0/{len(urls)} · 準備中…"), text_color=TXT_HI)
        status.configure(text="處理中…", text_color=GOLD)
        model = MODELS.get(quality_seg.get(), "small")
        category = safe_cat(cat_combo.get())
        threading.Thread(target=worker,
                         args=(urls, lang_entry.get().strip(), depth_seg.get(), model, category),
                         daemon=True).start()
        root.after(80, drain)

    def on_cancel():
        if not st["busy"]:
            return
        ctrl["cancel"].set()
        p = ctrl.get("proc")
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass
        cancel_btn.configure(state="disabled", text="取消中…")
        step_lab.configure(text="取消中…（等目前步驟收尾）", text_color=RED)
        status.configure(text="取消中…", text_color=RED)

    def open_article():
        if st["last_article"] and os.path.exists(st["last_article"]):
            os.startfile(st["last_article"])

    def open_folder():
        if st["last_dir"]:
            os.startfile(st["last_dir"])

    def on_export():
        d = st.get("last_dir")
        if not d or not os.path.isdir(d):
            return
        export_btn.configure(state="disabled", text="匯出中…")

        def work():
            try:
                subprocess.run([PY, str(EXPORT), d], creationflags=NO_WINDOW,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            except Exception:
                pass

            def done():
                export_btn.configure(state="normal", text="↧ 匯出檔")
                try:
                    os.startfile(d)
                except Exception:
                    pass
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def on_send_obsidian():
        d = st.get("last_dir")
        if not d or not os.path.isdir(d):
            return
        obsidian_btn.configure(state="disabled", text="送出中…")

        def work():
            res = {}
            try:
                p = subprocess.run([PY, str(EXPORT), d, "--vault", "auto"], creationflags=NO_WINDOW,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                for line in (p.stdout or "").splitlines():
                    if line.strip().startswith("{"):
                        res = json.loads(line.strip())
                        break
            except Exception as e:
                res = {"vault_error": str(e)[:60]}

            def done():
                obsidian_btn.configure(state="normal", text="📥 送到 Obsidian")
                if res.get("vault_note"):
                    status.configure(text="已送進 Obsidian ✓（影片文章 夾）", text_color=GREEN)
                    try:
                        os.startfile(str(Path(res["vault_note"]).parent))
                    except Exception:
                        pass
                else:
                    status.configure(text="送 Obsidian 失敗：" + (res.get("vault_error") or "未知"), text_color=RED)
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def open_index():
        run_build_index()
        idx = BASE / "index.html"
        if idx.exists():
            os.startfile(str(idx))

    def do_relogin():
        # 開一個新終端機跑標準登入（claude auth login，subscription）；完成後回 GUI 重按開始即可
        opened = False
        for cmd in ('cmd /k claude auth login', 'cmd /k claude setup-token'):
            try:
                subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                opened = True
                break
            except Exception:
                continue
        if not opened:
            try:
                os.system('start cmd /k claude auth login')
                opened = True
            except Exception:
                pass
        status.configure(
            text=("登入視窗已開啟：在跳出的視窗完成瀏覽器登入（選 Claude 訂閱）後，回來重按「開始作業」"
                  if opened else "無法自動開啟終端機，請手動在終端機執行：claude auth login"),
            text_color=GOLD)

    start_btn.configure(command=on_start)
    cancel_btn.configure(command=on_cancel)
    open_btn.configure(command=open_article)
    folder_btn.configure(command=open_folder)
    export_btn.configure(command=on_export)
    obsidian_btn.configure(command=on_send_obsidian)
    index_btn.configure(command=open_index)
    relogin_btn.configure(command=do_relogin)
    url_box.focus_set()

    if "--smoketest" in sys.argv:
        root.after(800, root.destroy)
    root.mainloop()


# ---------------------------------------------------------------------------
def main():
    # CLI 模式（--writeonly/--selftest）可能在 cp950 主控台執行，emoji/✗ 會 UnicodeEncodeError；
    # 強制 stdout/stderr 走 UTF-8（GUI/pythonw 下 stdout 為 None，try 內安全略過）
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if "--selftest" in sys.argv:
        url = sys.argv[-1]
        info = run_fetch(url, None, None, None, lambda s: print(s))
        print(json.dumps(info, ensure_ascii=False, indent=2))
        if info.get("ok") and "--write" in sys.argv:
            ok = write_article_via_claude(info["out_dir"], "逐節精讀", lambda s: print(s))
            print("WROTE_ARTICLE:", ok)
        return
    # 只重寫、不重抓：撰寫那步失敗時，transcript 已在夾內，用這個重跑撰寫＋渲染即可
    #   python launcher.pyw --writeonly "<輸出夾>" [--mode 逐節精讀|快覽|逐字精修]
    if "--writeonly" in sys.argv:
        wi = sys.argv.index("--writeonly")
        if wi + 1 >= len(sys.argv):
            print('用法：launcher.pyw --writeonly "<輸出夾>" [--mode 逐節精讀|快覽|逐字精修]')
            return
        d = sys.argv[wi + 1]
        mode = "逐節精讀"
        if "--mode" in sys.argv:
            mi = sys.argv.index("--mode")
            if mi + 1 < len(sys.argv):
                mode = sys.argv[mi + 1]
        ok = write_article_via_claude(d, mode, lambda s: print(s))
        print("WROTE_ARTICLE:", ok)
        return
    start_gui()


if __name__ == "__main__":
    main()
