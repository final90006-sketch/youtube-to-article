#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
lint_article.py — 對話版「產後完整性審計」CLI（零 LLM、確定性、只報不擋）

背景：桌面 GUI（launcher.pyw）在 claude -p 產出文章後，會跑一套零 LLM 的機械品質門
（佔位搪塞語偵測／份量樓地板／時間碼審計），寫成 _quality_report.txt。
現在改成「對話版為主、GUI 降級」：Claude 在對話中直接寫 article.md，不經過 GUI，
但那套機械品質門仍有價值、不該只綁在 GUI 上。本檔把它抽成獨立 CLI，供對話版跑，
也讓未來真要砍 GUI 時這條防線不會跟著消失。

用法：
    py -3 scripts/lint_article.py "<文章夾路徑>" [--mode 逐節精讀|快覽|逐字精修] [--doc] [--json]

輸入（唯讀，本檔不寫入任何檔案，只印到 stdout）：
    <文章夾>/article.md         必要。找不到＝用法錯誤（退出碼 2），不是品質判定。
    <文章夾>/transcript.json    選用。有的話才能做份量比／時間碼審計；
                                 沒有就只做基本長度／結構／佔位搪塞審計。
    <文章夾>/transcript.txt     選用。若存在優先當逐字稿全文（比 segments 拼接更貼近原文）。

退出碼：
    0 = 審計已完成（不論有沒有 WARN——只報不擋，跟 launcher.pyw._write_quality_report 同精神）
    2 = 用法錯誤（資料夾不存在／article.md 不存在／transcript.json 存在但解析失敗且無法降級）

--------------------------------------------------------------------------------------------
SYNC NOTE（本檔刻意不 import launcher.pyw——GUI 檔以後可能被砍，這支 CLI 要能獨立存活；
只依賴 common.py，那是本技能夾唯一跨腳本共用的定義處）。
下列邏輯／常數逐字複製自 launcher.pyw（讀取當下的行號，供未來人工核對是否漂移；
複製時「一個字都不改」——含黑名單詞、容忍值、比例地板）：

    launcher.pyw 符號                行號         複製到本檔
    -------------------------------  -----------  --------------------------------
    _PLACEHOLDERS                    L361-363     _PLACEHOLDERS（逐字複製）
    _find_placeholders               L366-367     _find_placeholders（邏輯相同）
    _make_body_validator             L452-469     份量樓地板公式
                                                   floor = max(150, chunk_chars*0.10)
                                                   → 拆解成獨立 PASS/WARN 檢查項，而非呼叫
                                                     原本會「一命中就短路」的單一 validator，
                                                     因為 lint 工具要把所有問題都列出來，
                                                     不能像生成期重試邏輯那樣只回報第一個。
    _write_quality_report            L551-599     佔位／整篇長度比 0.35 樓地板／
                                                   時間碼單調性（120s 容忍、15% 門檻）／
                                                   各塊時間覆蓋（60s 容忍）—— 逐項複製，
                                                   閾值一律不改。
    _split_by_chapters               L382-420     _split_by_chapters（逐字複製）
    _split_segments                  L423-443     _split_segments（逐字複製）
    CHUNK_BODY_CHARS = 12000         L334         CHUNK_BODY_CHARS
    CHUNK_MAX = 24                   L335         CHUNK_MAX

若 launcher.pyw 上述邏輯／常數有異動，本檔需要人工重新核對同步（本檔測試不會自動抓到
GUI 那邊的變動，因為刻意解耦）。
--------------------------------------------------------------------------------------------
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from common import TS_PAT, TS_PAT3, hms  # noqa: E402  （唯一允許的跨腳本依賴）


# ---------------------------------------------------------------------------
# 逐字複製自 launcher.pyw（見檔頭 SYNC NOTE）
# ---------------------------------------------------------------------------
_PLACEHOLDERS = ("見正文", "省略重貼", "以下省略", "（後略）", "(後略)", "內容中斷", "此處中斷",
                 "未在本片段範圍", "本段在此處結束", "省略不貼", "內容相同，省略", "其餘同上",
                 "篇幅所限", "餘略", "【略】", "[略]")

CHUNK_BODY_CHARS = 12000
CHUNK_MAX = 24


def _find_placeholders(text):
    return [p for p in _PLACEHOLDERS if p in (text or "")]


def _fmt_t(sec):
    return hms(max(0, int(sec or 0)))


def _split_by_chapters(chapters, segments, max_chars, max_chunks=CHUNK_MAX):
    """章節對齊切塊（結構邊界優先）：章節邊界＝硬切點，塊內按字數上限打包相鄰章節；
       單章過大才在章內按字數細切；無章節（<2）或無 segments 回 []（由呼叫端回退等字數）。"""
    chs = [c for c in (chapters or []) if c.get("title") and c.get("start") is not None]
    segs = [s for s in (segments or []) if s.get("text")]
    if len(chs) < 2 or not segs:
        return []
    bounds = [float(c.get("start") or 0) for c in chs]
    groups = [[] for _ in chs]
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
        if n > max_chars * 1.5:
            if buf:
                chunks.append(buf)
                buf, bufn = [], 0
            chunks.extend(_split_segments(g, max_chars, max_chunks))
        elif buf and bufn + n > max_chars:
            chunks.append(buf)
            buf, bufn = list(g), n
        else:
            buf.extend(g)
            bufn += n
    if buf:
        chunks.append(buf)
    while len(chunks) > max_chunks:
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
    for _ in range(12):
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
    return chunks


# ---------------------------------------------------------------------------
# 審計本體
# ---------------------------------------------------------------------------
def lint_article(folder: Path, mode="逐節精讀", force_doc=None):
    """對 <folder>/article.md 跑產後完整性審計。回傳 dict（不寫任何檔案）。
       folder 不存在或 article.md 不存在 → 回傳 None（用法錯誤，由呼叫端決定退出碼）。"""
    article_path = folder / "article.md"
    if not folder.is_dir() or not article_path.exists():
        return None

    article = article_path.read_text(encoding="utf-8", errors="replace")
    checks = []
    warn_count = 0

    def add(name, ok, detail):
        nonlocal warn_count
        checks.append({"name": name, "status": "PASS" if ok else "WARN", "detail": detail})
        if not ok:
            warn_count += 1

    # --- 基本長度 / 結構（同 _make_body_validator 的 EMPTY / INCOMPLETE 判準）---
    add("基本長度（EMPTY 判準 <150 字）", len(article) >= 150,
        f"article.md 共 {len(article):,} 字")
    add("結構（是否含 \"##\" 小節標題）", "##" in article,
        "找不到任何 \"##\" 小節標題" if "##" not in article else "含 \"##\" 小節標題")

    # --- 佔位搪塞語（同 _find_placeholders，逐字複製黑名單）---
    ph = _find_placeholders(article)
    add("佔位搪塞語黑名單", not ph,
        f"命中：{'、'.join(ph)}" if ph else "無佔位搪塞語")

    result = {
        "folder": str(folder),
        "article_chars": len(article),
        "mode": mode,
        "checks": checks,
        "warn_count": warn_count,
        "notes": [],
    }

    # --- transcript.json（選用；沒有就只做上面三項，其餘略過）---
    tpath = folder / "transcript.json"
    if not tpath.exists():
        result["notes"].append("無 transcript.json：只做基本長度／結構／佔位審計，"
                                "略過份量樓地板與時間碼審計。")
        result["warn_count"] = warn_count
        return result

    try:
        data = json.loads(tpath.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        result["notes"].append(f"transcript.json 解析失敗（{e}）：略過份量樓地板與時間碼審計。")
        return result

    meta = data.get("meta", {}) or {}
    doc = (meta.get("type") or "av") == "document" if force_doc is None else force_doc
    segments = [s for s in (data.get("segments") or []) if s.get("text")]
    chapters = data.get("chapters") or []

    txt_path = folder / "transcript.txt"
    if txt_path.exists():
        ttxt = txt_path.read_text(encoding="utf-8", errors="replace")
    else:
        ttxt = "\n".join(s.get("text", "") for s in segments)

    # --- 份量樓地板：整篇比例（同 _write_quality_report，樓地板 0.35；mode=快覽 時原本就不查）---
    if mode != "快覽" and ttxt:
        ratio = len(article) / len(ttxt)
        add("份量樓地板（文章／逐字稿長度比，樓地板 0.35）", ratio >= 0.35,
            f"比例 {ratio:.2f}（文章 {len(article):,} 字／逐字稿 {len(ttxt):,} 字）")
    elif mode == "快覽":
        result["notes"].append("mode=快覽：略過份量樓地板檢查（同 launcher.pyw 行為）。")

    # --- 份量樓地板：同 _make_body_validator 的 SHORT 判準，把整篇文章當成唯一一塊 ---
    if ttxt:
        floor = max(150, int(len(ttxt) * 0.10))
        add(f"份量樓地板（單塊 10% 地板，同 _make_body_validator，地板 {floor:,} 字）",
            len(article) >= floor,
            f"文章 {len(article):,} 字 vs 地板 {floor:,} 字（= max(150, 逐字稿字數*0.10)）")

    if doc:
        result["notes"].append("type=document：無秒級時間軸，略過時間碼單調性／覆蓋審查"
                                "（同 launcher.pyw 行為）。")
        return result

    # --- 時間碼存在（同 _make_body_validator 的 NOTIME 判準）---
    has_ts = bool(re.search(TS_PAT, article))
    add("時間碼存在（NOTIME 判準）", has_ts, "有 [MM:SS] 時間碼" if has_ts else "文章中找不到任何 [MM:SS] 時間碼")

    # --- 時間碼單調性（同 _write_quality_report：120 秒容忍、倒退比門檻 15%）---
    ts = [(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m.group(3)
          else (int(m.group(1)) * 60 + int(m.group(2)))
          for m in re.finditer(TS_PAT3, article)]
    if len(ts) >= 2:
        inv = sum(1 for a, b in zip(ts, ts[1:]) if b < a - 120)
        frac = inv / (len(ts) - 1)
        add("時間碼單調性（容忍 2 分鐘內回指、倒退比門檻 15%）", frac <= 0.15,
            f"{len(ts)} 個時間碼、倒退比 {frac:.0%}")
    else:
        result["notes"].append(f"文章中時間碼樣本數 {len(ts)} 個（<2），不足以判定單調性，略過。")

    # --- 各塊時間覆蓋（同 _write_quality_report：60 秒容忍；塊由 chapters/segments 重建）---
    chunks = []
    how = ""
    if segments:
        chunks = _split_by_chapters(chapters, segments, CHUNK_BODY_CHARS)
        how = "章節對齊"
        if len(chunks) < 2:
            chunks = _split_segments(segments, CHUNK_BODY_CHARS)
            how = "等字數"
    if len(chunks) >= 2:
        for i, seg in enumerate(chunks, 1):
            tt = [s.get("t") or 0 for s in seg if s.get("text")]
            if not tt:
                continue
            t0, t1 = min(tt), max(tt)
            hit = any(t0 - 60 <= x <= t1 + 60 for x in ts)
            add(f"第 {i}/{len(chunks)} 塊時間覆蓋（{_fmt_t(t0)}–{_fmt_t(t1)}，切法={how}）",
                hit,
                "有對應時間碼" if hit
                else f"文章裡找不到落在 {_fmt_t(t0)}–{_fmt_t(t1)}（±60秒）內的時間碼，"
                     "疑似此段內容漏寫或濃縮過度")
    else:
        result["notes"].append("transcript.json 的 segments 不足以重建切塊，略過各塊時間覆蓋審計。")

    result["warn_count"] = sum(1 for c in checks if c["status"] == "WARN")
    return result


# ---------------------------------------------------------------------------
# 輸出格式
# ---------------------------------------------------------------------------
def format_report(result: dict) -> str:
    lines = []
    lines.append(f"文章完整性審計：{result['folder']}")
    lines.append(f"（article.md {result['article_chars']:,} 字，mode={result['mode']}）")
    lines.append("-" * 60)
    for c in result["checks"]:
        lines.append(f"[{c['status']}] {c['name']}")
        lines.append(f"       {c['detail']}")
    for n in result.get("notes", []):
        lines.append(f"[NOTE] {n}")
    lines.append("-" * 60)
    wc = result["warn_count"]
    lines.append("審計結果：全部通過" if wc == 0 else f"審計結果：{wc} 項警告（只報不擋，請自行判斷是否需要修正）")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="對話版文章完整性 lint（從 launcher.pyw 的產後審計抽出的獨立 CLI，零 LLM、只報不擋）")
    ap.add_argument("folder", help="文章資料夾路徑（需含 article.md；若有 transcript.json 會一併審計份量／時間碼）")
    ap.add_argument("--mode", default="逐節精讀", choices=["逐節精讀", "快覽", "逐字精修"],
                     help="同 launcher.pyw 的撰寫模式；快覽會略過份量比檢查（預設：逐節精讀）")
    ap.add_argument("--doc", action="store_true",
                     help="強制視為 type=document（無秒級時間軸，略過時間碼審計）；"
                          "未指定則從 transcript.json 的 meta.type 自動判斷")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式輸出（供機器讀取）")
    args = ap.parse_args()

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    folder = Path(args.folder)
    result = lint_article(folder, mode=args.mode, force_doc=(True if args.doc else None))
    if result is None:
        print(f"✗ 用法錯誤：{folder} 不是資料夾，或找不到 {folder / 'article.md'}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    sys.exit(0)   # 只報不擋：審計本身跑完就是 0，不論有沒有 WARN


if __name__ == "__main__":
    main()
