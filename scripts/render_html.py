#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
render_html.py — 把 Claude 寫好的 article.md 渲染成「精緻權威閱讀版」article.html

設計：navy(#1B2A4A)/gold(#B8932E) 權威識別、思源宋體標題＋思源黑體內文、
單檔自含（inline CSS＋JS、可離線雙擊開啟）。修掉舊版「字體不一致／離線掉到
新細明體」的毛病：字型 local() 優先、堆疊永不含 PMingLiU。

新增 premium 功能（皆純前端、優雅降級）：
  - 頂部工具列：複製全文 / 匯出 Markdown / 列印·存PDF / 深色模式
  - 閱讀進度條、章節導覽側欄（scroll-spy）、手機抽屜
  - 💡 重點洞察卡片、⚡ 可帶走的行動（可勾選，localStorage 記憶）
  - ❝ 金句卡（可複製＋跳片）、callout 強調框
  - 逐字稿摺疊（由 transcript.json 注入，每行可跳回原片）

Markdown 子集：# / ## / ###、段落、**粗體**、*斜體*、`碼`、> 引言、
  - / 1. 清單、--- 分隔線、| 表格 |、[文字](網址)、[mm:ss] 時間碼，
  以及 callout：> [!key] / [!note] / [!warn] / [!quote]。
  依標題名（含「重點洞察」「可應用/帶得走/行動」「金句」）自動渲染成卡片/清單/金句。

用法:
    python render_html.py --md article.md --json transcript.json --out article.html
"""

import argparse
import html
import json
import re
from pathlib import Path

for _s in ("stdout", "stderr"):
    try:
        getattr(__import__("sys"), _s).reconfigure(encoding="utf-8")
    except Exception:
        pass

from common import TS_PAT, SRC_MAP_HERO, ts_to_seconds, hms  # noqa: E402（P0-3 常數收斂）


def strip_md(t):
    t = re.sub(TS_PAT, "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[*`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_title(raw):
    t = re.sub(TS_PAT, "", raw).replace("*", "").replace("`", "")
    return t.strip(" 　·•💡⚡❝🔑📌▸▶").strip() or raw.strip()


# ---------------------------------------------------------------------------
# 行內格式
# ---------------------------------------------------------------------------
def make_inline(video_url):
    ts_re = re.compile(TS_PAT)
    link_re = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    code_re = re.compile(r"`([^`]+)`")
    bold_re = re.compile(r"\*\*([^*]+)\*\*")
    ital_re = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")

    def build_ts(sec):
        # 只有 YouTube 支援 ?t=秒 跳片；其他平台（X/Vimeo…）時間碼僅當標記、不連結
        if not video_url or not ("youtube.com" in video_url or "youtu.be" in video_url):
            return None
        sep = "&" if "?" in video_url else "?"
        return f"{video_url}{sep}t={sec}s"

    def inline(text):
        links = []

        def stash_link(m):
            links.append((m.group(1), m.group(2)))
            return f"\x00L{len(links)-1}\x00"

        text = link_re.sub(stash_link, text)

        codes = []

        def stash_code(m):
            codes.append(m.group(1))
            return f"\x00C{len(codes)-1}\x00"

        text = code_re.sub(stash_code, text)        # 先抽走行內碼，避免 **/* 滲入碼內或跨 <code> 邊界
        text = html.escape(text)

        def ts_sub(m):
            ts = m.group(1)
            url = build_ts(ts_to_seconds(ts))
            if url:
                return f'<a class="ts" href="{url}" target="_blank" rel="noopener">{ts}</a>'
            return f'<span class="ts ts-flat">{ts}</span>'

        text = ts_re.sub(ts_sub, text)
        text = bold_re.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
        text = ital_re.sub(lambda m: f"<em>{m.group(1)}</em>", text)
        for i, c in enumerate(codes):               # 還原行內碼（內容照實轉義、不套任何格式）
            text = text.replace(f"\x00C{i}\x00", f"<code>{html.escape(c)}</code>")

        def restore(m):
            i = int(m.group(1))
            t, u = links[i]
            return f'<a href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(t)}</a>'

        return re.sub(r"\x00L(\d+)\x00", restore, text)

    return inline


def section_kind(title_plain):
    t = title_plain
    if "重點洞察" in t or "關鍵洞察" in t:
        return "insight"
    if ("可應用" in t) or ("帶得走" in t) or ("可帶走" in t) or ("行動" in t):
        return "action"
    if "金句" in t:
        return "quote"
    if ("自我檢核" in t) or ("自我檢測" in t) or ("複習" in t) or ("測驗" in t):
        return "quiz"
    return "normal"


def split_qa(item):
    """把『問題｜答案』拆成 (q, a)；支援 ｜ || —— :: | 作分隔，無分隔則整句當問題。"""
    for sep in ("｜", "||", " —— ", "——", " :: ", "::"):
        if sep in item:
            q, a = item.split(sep, 1)
            return q.strip(), a.strip()
    if "|" in item:
        q, a = item.split("|", 1)
        return q.strip(), a.strip()
    return item.strip(), ""


def quote_card(text_md, inline):
    plain = strip_md(text_md)
    return (f'<figure class="quote">{inline(text_md)}'
            f'<button class="q-copy" data-q="{html.escape(plain)}" title="複製金句" aria-label="複製金句">⧉</button>'
            f"</figure>")


# ---------------------------------------------------------------------------
# Markdown → HTML（單趟掃描，依標題名分流；回傳 body, toc, stats）
# ---------------------------------------------------------------------------
def md_to_html(md, video_url):
    inline = make_inline(video_url)
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    toc = []
    doc_title = None
    n_insights = 0
    n_h2_normal = 0          # kind==normal 的 h2 數（document 型 stats 用；av 不看這個）
    sec_no = 0
    i, n = 0, len(lines)
    para = []

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para).strip()) + "</p>")
            para.clear()

    def skip_blanks(j):
        while j < n and not lines[j].strip():
            j += 1
        return j

    def collect_list(j):
        items = []
        while j < n and re.match(r"\s*[-*+]\s+", lines[j]):
            items.append(re.sub(r"^\s*[-*+]\s+", "", lines[j]).strip())
            j += 1
        return items, j

    def collect_quote_block(j):
        q = []
        while j < n and lines[j].strip().startswith(">"):
            q.append(re.sub(r"^\s*>\s?", "", lines[j]))
            j += 1
        return " ".join(x.strip() for x in q).strip(), j

    while i < n:
        s = lines[i].strip()

        if not s:
            flush_para()
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        mh = re.match(r"(#{1,6})\s+(.*)", s)
        if mh:
            flush_para()
            level = len(mh.group(1))
            raw = mh.group(2).strip()
            if level == 1:
                # 首個 # 標題當作整篇標題（給 hero 用），不在內文重複呈現
                if doc_title is None:
                    doc_title = strip_md(raw)
                else:
                    out.append(f"<h1>{inline(raw)}</h1>")
                i += 1
                continue
            if level == 2:
                sec_no += 1
                sid = f"sec-{sec_no}"
                tsm = re.search(TS_PAT, raw)
                secs = ts_to_seconds(tsm.group(1)) if tsm else None
                toc.append({"id": sid, "title": clean_title(raw), "secs": secs})
                kind = section_kind(clean_title(raw))

                if kind == "insight":
                    j = skip_blanks(i + 1)
                    items, j = collect_list(j)
                    out.append(f'<section class="sec sec-insight"><h2 id="{sid}">{inline(raw)}</h2>')
                    out.append('<div class="insight-grid">')
                    for k, it in enumerate(items, 1):
                        n_insights += 1
                        out.append(f'<div class="insight"><div class="insight-no">{k:02d}</div>'
                                   f'<div class="insight-tx">{inline(it)}</div></div>')
                    out.append("</div></section>")
                    i = j
                    continue

                if kind == "action":
                    j = skip_blanks(i + 1)
                    items, j = collect_list(j)
                    out.append(f'<section class="sec sec-action"><h2 id="{sid}">{inline(raw)}</h2>')
                    out.append('<div class="checklist">')
                    for k, it in enumerate(items):
                        out.append(f'<label class="task"><input type="checkbox" data-k="ta-{k}">'
                                   f'<span>{inline(it)}</span></label>')
                    out.append("</div></section>")
                    i = j
                    continue

                if kind == "quiz":
                    jj = skip_blanks(i + 1)
                    items, jj = collect_list(jj)
                    out.append(f'<section class="sec sec-quiz"><div class="quiz-head">'
                               f'<h2 id="{sid}">{inline(raw)}</h2>'
                               f'<button class="anki-btn" title="匯出成 Anki 可匯入的檔（問題與答案以 Tab 分隔）">'
                               f'↧ 匯出 Anki</button></div>')
                    out.append('<div class="quizgrid">')
                    for k, it in enumerate(items, 1):
                        qq, aa = split_qa(it)
                        out.append(
                            f'<div class="qz" data-q="{html.escape(strip_md(qq))}" '
                            f'data-a="{html.escape(strip_md(aa))}">'
                            f'<div class="qz-q"><span class="qz-no">Q{k}</span>{inline(qq)}</div>'
                            f'<div class="qz-a">{inline(aa)}</div>'
                            f'<span class="qz-hint">點一下看答案</span></div>')
                    out.append("</div></section>")
                    i = jj
                    continue

                if kind == "quote":
                    out.append(f'<section class="sec sec-quote"><h2 id="{sid}">{inline(raw)}</h2>')
                    j = skip_blanks(i + 1)
                    while j < n and lines[j].strip().startswith(">"):
                        block, j = collect_quote_block(j)
                        block = re.sub(r"^\[!quote\]\s*", "", block)
                        out.append(quote_card(block, inline))
                        j = skip_blanks(j)
                    out.append("</section>")
                    i = j
                    continue

                n_h2_normal += 1
                out.append(f'<h2 id="{sid}">{inline(raw)}</h2>')
                i += 1
                continue
            # h3..h6
            out.append(f"<h{level}>{inline(raw)}</h{level}>")
            i += 1
            continue

        # 引言 / callout（連續 >）
        if s.startswith(">"):
            flush_para()
            block, i = collect_quote_block(i)
            m = re.match(r"\[!(key|note|warn|quote)\]\s*(.*)", block, re.S)
            if m:
                ctype, rest = m.group(1), m.group(2)
                if ctype == "quote":
                    out.append(quote_card(rest, inline))
                else:
                    label = {"key": "重點", "note": "提示", "warn": "注意"}[ctype]
                    out.append(f'<div class="callout {ctype}"><span class="cl-lab">{label}</span>'
                               f'<div class="cl-tx">{inline(rest)}</div></div>')
            else:
                out.append(f"<blockquote>{inline(block)}</blockquote>")
            continue

        # 表格
        if s.startswith("|") and "|" in s[1:]:
            flush_para()
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            out.append(render_table(tbl, inline))
            continue

        # 無序清單
        if re.match(r"[-*+]\s+", s):
            flush_para()
            items, i = collect_list(i)
            out.append("<ul>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ul>")
            continue

        # 有序清單
        if re.match(r"\d+[.)]\s+", s):
            flush_para()
            items = []
            while i < n and re.match(r"\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]).strip())
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ol>")
            continue

        para.append(s)
        i += 1

    flush_para()

    plain = re.sub(TS_PAT, "", re.sub(r"[#>*`|]", " ", md))
    chars = len(re.sub(r"\s+", "", plain))
    read_min = max(1, round(chars / 450))
    n_chapters = sum(1 for t in toc if t["secs"] is not None)
    stats = {"read_min": read_min, "n_chapters": n_chapters, "n_insights": n_insights,
             "n_h2_normal": n_h2_normal}
    return "\n".join(out), toc, stats, doc_title


def render_table(rows, inline):
    def cells(r):
        return [c.strip() for c in r.strip().strip("|").split("|")]

    if not rows:
        return ""
    header = cells(rows[0])
    body = rows[1:]
    if body and re.fullmatch(r"[\s|:\-]+", "|".join(cells(body[0]))):
        body = body[1:]
    h = "".join(f"<th>{inline(c)}</th>" for c in header)
    out = [f'<div class="tbl-wrap"><table><thead><tr>{h}</tr></thead><tbody>']
    for r in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_transcript(segments, video_url):
    if not segments:
        return ""
    yt = bool(video_url) and ("youtube.com" in video_url or "youtu.be" in video_url)
    rows = []
    for seg in segments:
        t = seg.get("t", 0)
        txt = html.escape((seg.get("text") or "").replace("\n", " ").strip())
        if not txt:
            continue
        if yt:
            sep = "&" if "?" in video_url else "?"
            href = f'{video_url}{sep}t={int(t)}s'
            rows.append(f'<a class="tx-line" href="{href}" target="_blank" rel="noopener">'
                        f'<span class="tx-t">{hms(t)}</span><span class="tx-x">{txt}</span></a>')
        else:
            rows.append(f'<div class="tx-line"><span class="tx-t">{hms(t)}</span>'
                        f'<span class="tx-x">{txt}</span></div>')
    return ('<details class="transcript"><summary>逐字稿　·　點任一行跳回原片</summary>'
            '<div class="tx-ctrl"><button class="tx-auto" type="button">▶ 自動捲動</button>'
            '<label class="tx-spd">速度 <select class="tx-speed">'
            '<option value="1">慢</option><option value="2" selected>中</option>'
            '<option value="4">快</option></select></label></div>'
            '<div class="tx-body">' + "".join(rows) + "</div></details>")


# ---------------------------------------------------------------------------
# 樣式與腳本（純字面字串，無 .format，避免大括號轉義地獄）
# ---------------------------------------------------------------------------
CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@500;700;900&family=Noto+Sans+TC:wght@400;500;700;900&display=swap');
@font-face{font-family:"AppSans";font-display:swap;
  src:local("Noto Sans TC"),local("Source Han Sans TC"),local("思源黑體"),local("Microsoft JhengHei"),local("微軟正黑體"),local("Microsoft YaHei"),local("PingFang TC");}
@font-face{font-family:"AppSerif";font-display:swap;
  src:local("Noto Serif TC"),local("Source Han Serif TC"),local("思源宋體"),local("Songti TC"),local("STSong");}
:root{
  --font-sans:"AppSans","Noto Sans TC","Microsoft JhengHei","Microsoft YaHei",system-ui,"Segoe UI",sans-serif;
  --font-serif:"AppSerif","Noto Serif TC","Microsoft JhengHei",serif;
  --navy:#1B2A4A;--navy-2:#1e4d78;--gold:#B8932E;--gold-2:#b5740a;
  --ink:#102a43;--ink-2:#334155;--ink-3:#5b6b7f;--line:#dce4ed;
  --surface:#ffffff;--surface-2:#f4f8fc;--red:#b5202f;--green:#0e7a5f;
  --radius:14px;--shadow:0 1px 2px rgba(16,42,67,.05),0 6px 18px rgba(16,42,67,.06);--col:880px;
}
:root[data-theme="dark"]{
  --navy:#a9c4ec;--navy-2:#88b0e0;--gold:#d9b85a;--gold-2:#e3c873;
  --ink:#e8eef6;--ink-2:#c4d0e0;--ink-3:#93a3b8;--line:#243244;
  --surface:#0f1722;--surface-2:#0b121b;--red:#e0707a;--green:#5cc69f;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 22px rgba(0,0,0,.5);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--surface-2);color:var(--ink-2);
  font-family:var(--font-sans);font-size:18px;line-height:1.92;letter-spacing:.2px;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}

/* 進度條 */
#progress{position:fixed;top:0;left:0;height:3px;width:0;z-index:120;
  background:linear-gradient(90deg,var(--gold),var(--gold-2));transition:width .08s linear}

/* 工具列 */
.toolbar{position:sticky;top:0;z-index:100;display:flex;align-items:center;gap:12px;
  padding:10px 22px;border-bottom:1px solid var(--line);
  background:var(--surface);background:color-mix(in srgb,var(--surface) 86%,transparent);
  backdrop-filter:saturate(1.4) blur(8px);}
.tb-brand{font-family:var(--font-serif);font-weight:900;color:var(--navy);font-size:15px;letter-spacing:1px;white-space:nowrap}
.tb-brand b{color:var(--gold-2)}
.tb-actions{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.btn{font-family:var(--font-sans);font-size:13.5px;font-weight:700;color:var(--ink-2);
  background:transparent;border:1px solid var(--line);border-radius:10px;padding:7px 13px;cursor:pointer;
  transition:.15s;white-space:nowrap;line-height:1}
.btn:hover{border-color:var(--navy-2);color:var(--navy);background:color-mix(in srgb,var(--navy-2) 8%,var(--surface))}
.btn:active{transform:translateY(1px)}
.icon-btn{display:none;background:transparent;border:1px solid var(--line);border-radius:10px;
  width:38px;height:38px;font-size:17px;cursor:pointer;color:var(--ink-2)}

/* 版面 */
.layout{max-width:1240px;margin:0 auto;display:grid;grid-template-columns:250px minmax(0,1fr);gap:44px;padding:30px 32px 120px}
aside.toc{position:sticky;top:78px;align-self:start;max-height:calc(100vh - 100px);overflow:auto}
.toc-h{font-family:var(--font-sans);font-size:12px;font-weight:700;letter-spacing:2.5px;
  color:var(--gold-2);text-transform:uppercase;margin:0 0 12px 12px}
.toc-row{display:flex;align-items:center;gap:4px}
a.toc-link{flex:1;display:block;font-size:14px;color:var(--ink-3);text-decoration:none;
  padding:7px 12px;border-left:2px solid transparent;border-radius:0 6px 6px 0;transition:.15s;line-height:1.5}
a.toc-link:hover{color:var(--navy);background:var(--surface)}
a.toc-link.current{color:var(--navy);font-weight:700;border-left-color:var(--gold);
  background:color-mix(in srgb,var(--gold) 9%,var(--surface))}
a.toc-jump{flex-shrink:0;color:var(--ink-3);text-decoration:none;font-size:12px;padding:4px 7px;border-radius:6px}
a.toc-jump:hover{color:#fff;background:var(--gold-2)}

main.reading{max-width:var(--col);min-width:0}

/* Hero */
.hero{background:var(--surface);border:1px solid var(--line);border-top:6px solid var(--gold);
  border-radius:var(--radius);padding:30px 34px;box-shadow:var(--shadow);margin-bottom:34px}
.kicker{font-family:var(--font-sans);font-size:12px;font-weight:700;letter-spacing:3px;
  color:var(--gold-2);text-transform:uppercase;margin-bottom:10px}
.hero-title{font-family:var(--font-serif);font-size:33px;line-height:1.32;font-weight:900;
  color:var(--navy);margin:0 0 16px}
.hero-meta{font-size:14px;color:var(--ink-3);display:flex;flex-wrap:wrap;gap:6px 18px}
.hero-meta b{color:var(--navy);font-weight:700}
.hero-meta a{color:var(--gold-2);text-decoration:none}
.hero-meta a:hover{text-decoration:underline}
.stats{display:flex;gap:14px;margin-top:20px;flex-wrap:wrap}
.stat{flex:1;min-width:96px;background:var(--surface-2);border:1px solid var(--line);border-radius:11px;
  padding:12px 14px;text-align:center}
.stat b{display:block;font-family:var(--font-serif);font-size:25px;font-weight:900;color:var(--gold-2);line-height:1.1}
.stat span{font-size:12.5px;color:var(--ink-3)}

/* 標題 */
h1{font-family:var(--font-serif)}
main.reading h2{font-family:var(--font-serif);font-size:24px;font-weight:900;color:var(--navy);
  margin:44px 0 14px;padding-bottom:9px;border-bottom:2px solid var(--line);scroll-margin-top:74px}
main.reading h2::before{content:"";display:inline-block;width:8px;height:21px;background:var(--gold);
  border-radius:2px;margin-right:12px;vertical-align:-2px}
main.reading h3{font-family:var(--font-serif);font-size:20px;font-weight:700;color:var(--navy-2);
  margin:28px 0 10px;scroll-margin-top:74px}
p{margin:0 0 17px}
strong{color:var(--navy);font-weight:700}
:root[data-theme="dark"] strong{color:var(--navy-2)}
ul,ol{margin:0 0 18px;padding-left:1.45em}
li{margin:6px 0}
hr{border:none;border-top:1px solid var(--line);margin:34px 0}
a{color:var(--gold-2)}
code{font-family:Consolas,"SFMono-Regular",monospace;font-size:.86em;background:var(--surface-2);
  border:1px solid var(--line);padding:1px 6px;border-radius:5px;color:var(--gold-2)}

/* 重點洞察卡 */
.sec{margin:30px 0}
.insight-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(248px,1fr));gap:14px}
.insight{position:relative;background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--gold);
  border-radius:12px;padding:16px 18px 16px;box-shadow:var(--shadow)}
.insight-no{font-family:var(--font-serif);font-size:14px;font-weight:900;color:var(--gold-2);
  letter-spacing:1px;margin-bottom:6px}
.insight-tx{font-size:16px;line-height:1.7;color:var(--ink-2)}
.insight-tx strong{color:var(--navy)}

/* 可帶走的行動清單 */
.checklist{background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--green);
  border-radius:12px;padding:8px 20px;box-shadow:var(--shadow)}
.task{display:flex;gap:13px;align-items:flex-start;padding:11px 0;border-bottom:1px solid var(--line);cursor:pointer}
.task:last-child{border-bottom:none}
.task input{margin-top:5px;width:18px;height:18px;flex-shrink:0;accent-color:var(--green);cursor:pointer}
.task span{font-size:16px;line-height:1.7;color:var(--ink-2)}
.task input:checked + span{color:var(--ink-3);text-decoration:line-through}

/* 🧠 自我檢核 複習卡 */
.quiz-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.anki-btn{margin-left:auto;font-family:var(--font-sans);font-size:13px;font-weight:700;color:var(--ink-2);
  background:transparent;border:1px solid var(--line);border-radius:9px;padding:6px 12px;cursor:pointer}
.anki-btn:hover{border-color:var(--navy-2);color:var(--navy);background:color-mix(in srgb,var(--navy-2) 8%,var(--surface))}
.quizgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-top:6px}
.qz{background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--navy-2);border-radius:12px;
  padding:16px 18px;box-shadow:var(--shadow);cursor:pointer;transition:.15s}
.qz:hover{border-left-color:var(--gold)}
.qz-q{font-size:16px;line-height:1.7;color:var(--navy);font-weight:700}
:root[data-theme="dark"] .qz-q{color:var(--navy-2)}
.qz-no{display:inline-block;font-family:var(--font-serif);font-weight:900;color:var(--gold-2);margin-right:8px}
.qz-a{font-size:15.5px;line-height:1.75;color:var(--ink-2);margin-top:10px;padding-top:10px;
  border-top:1px dashed var(--line);display:none}
.qz.show .qz-a{display:block}
.qz-hint{display:block;margin-top:9px;font-size:12px;color:var(--gold-2);font-weight:700}
.qz.show .qz-hint{display:none}

/* 金句 */
figure.quote{position:relative;margin:18px 0;background:var(--surface);border-left:5px solid var(--gold);
  border-radius:0 12px 12px 0;padding:18px 52px 18px 24px;box-shadow:var(--shadow);
  font-family:var(--font-serif);font-size:19px;line-height:1.8;color:var(--navy)}
:root[data-theme="dark"] figure.quote{color:var(--ink)}
.q-copy{position:absolute;top:12px;right:12px;width:30px;height:30px;border-radius:8px;cursor:pointer;
  border:1px solid var(--line);background:var(--surface-2);color:var(--ink-3);font-size:14px;line-height:1}
.q-copy:hover{color:#fff;background:var(--gold-2);border-color:var(--gold-2)}

/* 引言 / callout */
blockquote{margin:20px 0;padding:14px 22px;background:var(--surface);border-left:5px solid var(--gold);
  border-radius:0 10px 10px 0;color:var(--ink-2);font-family:var(--font-serif);box-shadow:var(--shadow)}
.callout{display:flex;gap:14px;align-items:flex-start;margin:20px 0;padding:14px 20px;border-radius:11px;
  background:var(--surface);box-shadow:var(--shadow)}
.callout .cl-lab{flex-shrink:0;font-size:12.5px;font-weight:700;color:#fff;border-radius:6px;padding:3px 11px;margin-top:2px}
.callout .cl-tx{flex:1}
.callout.key{border-left:5px solid var(--navy-2);background:color-mix(in srgb,var(--navy-2) 7%,var(--surface))}
.callout.key .cl-lab{background:var(--navy-2)}
.callout.note{border-left:5px solid var(--gold-2);background:color-mix(in srgb,var(--gold-2) 8%,var(--surface))}
.callout.note .cl-lab{background:var(--gold-2)}
.callout.warn{border-left:5px solid var(--red);background:color-mix(in srgb,var(--red) 7%,var(--surface))}
.callout.warn .cl-lab{background:var(--red)}

/* 表格 */
.tbl-wrap{overflow-x:auto;margin:20px 0}
table{border-collapse:collapse;width:100%;font-size:15.5px;box-shadow:var(--shadow);
  border-radius:11px;overflow:hidden}
thead th{background:var(--navy);color:#fff;font-weight:700;padding:11px 14px;text-align:left}
:root[data-theme="dark"] thead th{background:#1c2c43;color:var(--ink)}
tbody td{padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top;background:var(--surface)}
tbody tr:nth-child(even) td{background:var(--surface-2)}

/* 時間碼膠囊 */
.ts{font-family:var(--font-sans);font-size:.74em;font-weight:700;color:var(--gold-2);
  background:color-mix(in srgb,var(--gold) 14%,var(--surface));border:1px solid color-mix(in srgb,var(--gold) 38%,var(--surface));
  padding:1px 8px;border-radius:20px;text-decoration:none;white-space:nowrap;vertical-align:1px;margin:0 2px}
a.ts:hover{background:var(--gold-2);color:#fff;border-color:var(--gold-2)}
.ts-flat{color:var(--ink-3);background:var(--surface-2);border-color:var(--line)}

/* 逐字稿 */
.transcript{margin:46px 0 0;background:var(--surface);border:1px solid var(--line);border-radius:12px;
  box-shadow:var(--shadow);overflow:hidden}
.transcript summary{cursor:pointer;padding:15px 20px;font-family:var(--font-serif);font-weight:700;
  font-size:16px;color:var(--navy);list-style:none}
.transcript summary::-webkit-details-marker{display:none}
.transcript summary::before{content:"▸ ";color:var(--gold-2)}
.transcript[open] summary::before{content:"▾ "}
.tx-ctrl{display:flex;align-items:center;gap:14px;padding:8px 20px;border-top:1px solid var(--line);background:var(--surface-2)}
.tx-auto{font-family:var(--font-sans);font-size:13px;font-weight:700;color:var(--ink-2);background:transparent;
  border:1px solid var(--line);border-radius:8px;padding:5px 12px;cursor:pointer}
.tx-auto:hover{border-color:var(--navy-2);color:var(--navy)}
.tx-auto.on{color:#fff;background:var(--gold-2);border-color:var(--gold-2)}
.tx-spd{font-size:12.5px;color:var(--ink-3)}
.tx-speed{font-family:var(--font-sans);font-size:12.5px;border:1px solid var(--line);border-radius:6px;
  padding:3px 6px;background:var(--surface);color:var(--ink-2)}
.tx-body{max-height:62vh;overflow:auto;border-top:1px solid var(--line);padding:6px 0}
.tx-line{display:flex;gap:12px;padding:5px 20px;text-decoration:none;color:var(--ink-2);font-size:14.5px;line-height:1.6}
.tx-line:hover{background:var(--surface-2)}
.tx-t{flex-shrink:0;font-variant-numeric:tabular-nums;color:var(--gold-2);font-weight:700;font-size:13px;min-width:52px;padding-top:1px}

footer.doc{margin:50px 0 0;padding-top:20px;border-top:1px solid var(--line);
  font-size:12.5px;color:var(--ink-3);text-align:center;line-height:1.7}

.overlay{display:none;position:fixed;inset:0;background:rgba(8,15,25,.5);z-index:90}
.overlay.show{display:block}

@media (max-width:1024px){
  .layout{grid-template-columns:1fr;padding:24px 18px 90px}
  aside.toc{position:fixed;top:0;left:0;bottom:0;width:280px;max-height:none;z-index:95;
    background:var(--surface);border-right:1px solid var(--line);padding:70px 14px 24px;
    transform:translateX(-105%);transition:transform .22s ease;box-shadow:0 0 40px rgba(0,0,0,.2)}
  aside.toc.open{transform:none}
  .icon-btn{display:inline-flex;align-items:center;justify-content:center}
  .hero-title{font-size:28px}
}
@media (max-width:560px){
  body{font-size:17px}
  .tb-brand{display:none}
  .hero{padding:22px 20px}.hero-title{font-size:25px}
  main.reading h2{font-size:21px}
  figure.quote{font-size:17px;padding:16px 46px 16px 18px}
}
@media print{
  #progress,.toolbar,aside.toc,.overlay,.transcript,.q-copy{display:none!important}
  body{background:#fff;font-size:12pt;line-height:1.7;color:#111}
  .layout{display:block;max-width:none;padding:0}
  main.reading{max-width:none}
  .hero,.insight,.checklist,figure.quote,blockquote,.callout,table{box-shadow:none}
  a[href]::after{content:""}
  main.reading h2,main.reading h3{break-after:avoid}
  .insight,figure.quote,.callout,table,.task{break-inside:avoid}
}
"""

THEME_INIT = """
(function(){try{var t=localStorage.getItem('vtp-theme');
if(!t){t=(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','light');}})();
"""

JS = r"""
(function(){
var data={};try{data=JSON.parse(document.getElementById('vtp-data').textContent);}catch(e){}
var root=document.documentElement;

function copyText(txt,btn,ok){
  function done(){if(btn){var o=btn.dataset.label||btn.textContent;btn.dataset.label=o;btn.textContent=ok;setTimeout(function(){btn.textContent=btn.dataset.label;},1500);}}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(done,function(){fb(txt);done();});}
  else{fb(txt);done();}
}
function fb(txt){try{var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();document.execCommand('copy');document.body.removeChild(ta);}catch(e){}}

var tbtn=document.getElementById('btn-theme');
function icon(t){if(tbtn)tbtn.textContent=(t==='dark'?'☀ 淺色':'🌙 深色');}
icon(root.getAttribute('data-theme'));
if(tbtn)tbtn.addEventListener('click',function(){var t=(root.getAttribute('data-theme')==='dark')?'light':'dark';root.setAttribute('data-theme',t);try{localStorage.setItem('vtp-theme',t);}catch(e){}icon(t);});

var cbtn=document.getElementById('btn-copy');
if(cbtn)cbtn.addEventListener('click',function(){var el=document.getElementById('copyscope');copyText(el?el.innerText:'',cbtn,'✓ 已複製');});

var ebtn=document.getElementById('btn-export');
if(ebtn)ebtn.addEventListener('click',function(){var md=data.md||'';var blob=new Blob([md],{type:'text/markdown;charset=utf-8'});var url=URL.createObjectURL(blob);var a=document.createElement('a');a.href=url;a.download='article.md';document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(url);},2000);});

var pbtn=document.getElementById('btn-print');
if(pbtn)pbtn.addEventListener('click',function(){window.print();});

var bar=document.getElementById('progress'),tick=false;
function prog(){var h=document.documentElement;var max=(h.scrollHeight-h.clientHeight)||1;if(bar)bar.style.width=(100*(h.scrollTop||document.body.scrollTop)/max)+'%';tick=false;}
window.addEventListener('scroll',function(){if(!tick){tick=true;requestAnimationFrame(prog);}},{passive:true});prog();

var toc=document.getElementById('toc'),ov=document.getElementById('overlay'),ham=document.getElementById('btn-menu');
function closeDrawer(){if(toc)toc.classList.remove('open');if(ov)ov.classList.remove('show');}
if(ham)ham.addEventListener('click',function(){if(toc)toc.classList.add('open');if(ov)ov.classList.add('show');});
if(ov)ov.addEventListener('click',closeDrawer);

var links={};
[].forEach.call(document.querySelectorAll('a.toc-link[data-target]'),function(a){
  links[a.getAttribute('data-target')]=a;
  a.addEventListener('click',function(e){var id=a.getAttribute('data-target');var el=document.getElementById(id);if(el){e.preventDefault();el.scrollIntoView({behavior:'smooth',block:'start'});history.replaceState(null,'','#'+id);closeDrawer();}});
});
var heads=[].slice.call(document.querySelectorAll('main.reading h2[id]'));
if(window.IntersectionObserver&&heads.length){
  var spy=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){var a=links[en.target.id];if(a){for(var k in links)links[k].classList.remove('current');a.classList.add('current');}}});},{rootMargin:'-45% 0px -50% 0px',threshold:0});
  heads.forEach(function(h){spy.observe(h);});
}

document.addEventListener('click',function(e){var b=e.target&&e.target.closest?e.target.closest('.q-copy'):null;if(b)copyText(b.getAttribute('data-q')||'',b,'✓');});

var ck='vtp-'+(data.vid||'x')+'-checks',st={};try{st=JSON.parse(localStorage.getItem(ck)||'{}');}catch(e){}
[].forEach.call(document.querySelectorAll('.task input[type=checkbox]'),function(cb){
  var k=cb.getAttribute('data-k');if(st[k])cb.checked=true;
  cb.addEventListener('change',function(){st[k]=cb.checked;try{localStorage.setItem(ck,JSON.stringify(st));}catch(e){}});
});

// 逐字稿自動捲動（念稿機模式）：可調速、到底自動停
[].forEach.call(document.querySelectorAll('.transcript'),function(det){
  var btn=det.querySelector('.tx-auto'),sel=det.querySelector('.tx-speed'),body=det.querySelector('.tx-body');
  if(!btn||!body)return;var timer=null;
  function stop(){if(timer){clearInterval(timer);timer=null;}btn.classList.remove('on');btn.textContent='▶ 自動捲動';}
  function start(){var spd=parseFloat((sel&&sel.value)||'2');btn.classList.add('on');btn.textContent='⏸ 暫停';
    timer=setInterval(function(){if(body.scrollTop+body.clientHeight>=body.scrollHeight-2){stop();return;}body.scrollTop+=spd;},50);}
  btn.addEventListener('click',function(){if(timer){stop();}else{start();}});
  if(sel)sel.addEventListener('change',function(){if(timer){stop();start();}});
});

// 🧠 自我檢核：點卡片翻看答案；匯出 Anki（問題\t答案，Anki 可直接匯入）
[].forEach.call(document.querySelectorAll('.qz'),function(c){
  c.addEventListener('click',function(){c.classList.toggle('show');});
});
[].forEach.call(document.querySelectorAll('.anki-btn'),function(btn){
  btn.addEventListener('click',function(e){
    e.stopPropagation();
    var rows=[];
    [].forEach.call(document.querySelectorAll('.qz'),function(c){
      var q=(c.getAttribute('data-q')||'').replace(/\t/g,' ').trim();
      var a=(c.getAttribute('data-a')||'').replace(/\t/g,' ').trim();
      if(q)rows.push(q+'\t'+a);
    });
    if(!rows.length)return;
    var blob=new Blob(['﻿'+rows.join('\n')],{type:'text/plain;charset=utf-8'});
    var url=URL.createObjectURL(blob);var a=document.createElement('a');
    a.href=url;a.download='自我檢核_anki.txt';document.body.appendChild(a);a.click();
    document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(url);},2000);
    var o=btn.textContent;btn.textContent='✓ 已匯出';setTimeout(function(){btn.textContent=o;},1500);
  });
});
})();
"""


def fmt_upload_date(d):
    if d and len(d) == 8:
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d or ""


def build_page(meta, track, body_html, toc, stats, transcript_html, md_raw, video_url, doc_title=None):
    is_doc = (meta.get("type") or "av") == "document"   # schema v2：缺欄位＝av
    title = html.escape(str(doc_title or meta.get("title", "影片文章")))

    meta_bits = []
    if meta.get("channel"):
        meta_bits.append(f'<span><b>頻道</b> {html.escape(str(meta["channel"]))}</span>')
    if meta.get("duration_str"):
        meta_bits.append(f'<span><b>時長</b> {html.escape(str(meta["duration_str"]))}</span>')
    if fmt_upload_date(meta.get("upload_date")):
        meta_bits.append(f'<span><b>發布</b> {fmt_upload_date(meta.get("upload_date"))}</span>')
    if track.get("source"):
        src_label = "來源" if is_doc else "字幕"
        meta_bits.append(f'<span><b>{src_label}</b> {SRC_MAP_HERO.get(track["source"], track["source"])}</span>')
    if video_url:
        is_yt = ("youtube.com" in video_url) or ("youtu.be" in video_url)
        link_label = "在 YouTube 觀看 ↗" if is_yt else "開啟原始連結 ↗"
        meta_bits.append(f'<span><a href="{html.escape(video_url)}" target="_blank" rel="noopener">{link_label}</a></span>')

    toc_rows = []
    for t in toc:
        jump = ""
        if t["secs"] is not None and video_url:
            sep = "&" if "?" in video_url else "?"
            jump = (f'<a class="toc-jump" href="{video_url}{sep}t={t["secs"]}s" target="_blank" '
                    f'rel="noopener" title="跳到影片 {hms(t["secs"])}">↗</a>')
        toc_rows.append(f'<div class="toc-row"><a class="toc-link" href="#{t["id"]}" '
                        f'data-target="{t["id"]}">{html.escape(t["title"])}</a>{jump}</div>')
    toc_html = "".join(toc_rows) or '<div class="toc-row"><span class="toc-link">（無章節）</span></div>'

    data_json = json.dumps({"md": md_raw, "vid": meta.get("id", ""), "video_url": video_url},
                           ensure_ascii=False).replace("</", "<\\/")

    # 文檔型（type=document）字樣分流；av 全維持原字面值（零回歸）
    kicker = "文檔精讀" if is_doc else "影片轉文章 · 逐節精讀"
    n_chapters = stats["n_h2_normal"] if is_doc else stats["n_chapters"]
    footer = ("本文由「影片轉文章」技能依原文整理生成 · 內容以原文為準" if is_doc else
              "本文由「影片轉文章」技能依字幕／語音辨識整理生成 · 內容以原片／原節目實際陳述為準 · 可點時間碼回看原片核對")

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<script>{THEME_INIT}</script>
<style>{CSS}</style>
</head>
<body>
<div id="progress"></div>
<header class="toolbar">
  <button class="icon-btn" id="btn-menu" aria-label="章節導覽">☰</button>
  <span class="tb-brand">影片<b>轉</b>文章</span>
  <div class="tb-actions">
    <button class="btn" id="btn-copy">⧉ 複製全文</button>
    <button class="btn" id="btn-export">↧ 匯出 Markdown</button>
    <button class="btn" id="btn-print">⎙ 列印 / 存 PDF</button>
    <button class="btn" id="btn-theme">🌙 深色</button>
  </div>
</header>
<div class="overlay" id="overlay"></div>
<div class="layout">
  <aside class="toc" id="toc">
    <div class="toc-h">章節導覽</div>
    <nav>{toc_html}</nav>
  </aside>
  <main class="reading">
    <section class="hero">
      <div class="kicker">{kicker}</div>
      <h1 class="hero-title">{title}</h1>
      <div class="hero-meta">{"".join(meta_bits)}</div>
      <div class="stats">
        <div class="stat"><b>{stats["read_min"]}</b><span>分鐘閱讀</span></div>
        <div class="stat"><b>{n_chapters}</b><span>章節</span></div>
        <div class="stat"><b>{stats["n_insights"]}</b><span>重點洞察</span></div>
      </div>
    </section>
    <div id="copyscope">
{body_html}
    </div>
    {transcript_html}
    <footer class="doc">{footer}</footer>
  </main>
</div>
<script id="vtp-data" type="application/json">{data_json}</script>
<script>{JS}</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    md = Path(args.md).read_text(encoding="utf-8")
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    track = data.get("track", {})
    segments = data.get("segments", [])
    # 假連結雷（P0-2）：只有影音型且 id 是 YouTube 11 碼格式才允許 fallback 合成 youtu.be，
    # document 型或非 YT id 一律空字串（別替 PDF/報告造出假影片連結）
    video_url = meta.get("webpage_url") or ""
    if not video_url and (meta.get("type") or "av") != "document":
        _mid = str(meta.get("id") or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", _mid):
            video_url = f"https://youtu.be/{_mid}"

    body_html, toc, stats, doc_title = md_to_html(md, video_url)
    transcript_html = render_transcript(segments, video_url)
    page = build_page(meta, track, body_html, toc, stats, transcript_html, md, video_url, doc_title)

    Path(args.out).write_text(page, encoding="utf-8")
    print(f"[OK] 已輸出精緻閱讀版 → {args.out}")
    print(f"     章節 {stats['n_chapters']} · 重點洞察 {stats['n_insights']} · 約 {stats['read_min']} 分鐘閱讀 · "
          f"逐字稿 {len(segments)} 段")


if __name__ == "__main__":
    main()
