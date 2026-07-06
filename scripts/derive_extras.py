#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
derive_extras.py — 從 article.md 確定性萃取三種衍生格式（零 LLM 呼叫、離線單檔 HTML）

  digest.html  一頁精華卡：標題/中繼資料 + 💡重點洞察 + ⚡行動清單 + ❝金句，A4 可列印
  mindmap.html 大綱心智圖：章節樹（##/###）＋每節前幾條要點，可摺疊、時間碼點回原片
  quiz.html    自測翻牌卡：🧠自我檢核 Q/A → 點卡翻面，「記住了/再複習」寫 localStorage

用法:
    python derive_extras.py "<影片輸出夾>"        # 夾內須有 article.md（transcript.json 選用）
輸出 JSON 一行：{"ok": true, "written": [...]}；來源缺區塊則該格式自動略過。
"""

import html
import json
import re
import sys
from pathlib import Path

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8")
    except Exception:
        pass

from common import TS_PAT3  # noqa: E402（P0-3 常數收斂；3 組變體，ts_seconds 靠分組取時分秒）

TS_PAT = re.compile(TS_PAT3)


def ts_seconds(m):
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def strip_md(t):
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t or "")
    t = re.sub(r"[*_`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# 解析 article.md
# ---------------------------------------------------------------------------
def parse_article(md):
    """回 dict：title / insights[] / actions[] / quotes[] / qa[(q,a)] / tree[{title,ts,children,points}]。"""
    doc = {"title": "", "insights": [], "actions": [], "quotes": [], "qa": [], "tree": []}
    cur_kind = ""            # insight / action / quote / qa / body / ''
    cur_node = None
    for line in (md or "").splitlines():
        s = line.strip()
        if s.startswith("# ") and not doc["title"]:
            doc["title"] = strip_md(TS_PAT.sub("", s[2:]))
            continue
        if s.startswith("## "):
            t = s[3:]
            plain = strip_md(TS_PAT.sub("", t))
            if ("重點洞察" in t) or ("關鍵洞察" in t):
                cur_kind, cur_node = "insight", None
            elif ("可應用" in t) or ("帶得走" in t) or ("可帶走" in t) or ("行動" in t and len(plain) < 20):
                cur_kind, cur_node = "action", None
            elif "金句" in t:
                cur_kind, cur_node = "quote", None
            elif ("自我檢核" in t) or ("自我檢測" in t) or ("複習" in t) or ("測驗" in t):
                cur_kind, cur_node = "qa", None
            else:
                cur_kind = "body"
                m = TS_PAT.search(t)
                cur_node = {"title": plain, "ts": ts_seconds(m) if m else None,
                            "label": m.group(0)[1:-1] if m else "", "children": [], "points": []}
                doc["tree"].append(cur_node)
            continue
        if s.startswith("### ") and cur_kind == "body" and cur_node is not None:
            m = TS_PAT.search(s)
            cur_node["children"].append({"title": strip_md(TS_PAT.sub("", s[4:])),
                                         "ts": ts_seconds(m) if m else None,
                                         "label": m.group(0)[1:-1] if m else ""})
            continue
        if s.startswith("- "):
            item = s[2:].strip()
            if cur_kind == "insight":
                doc["insights"].append(item)
            elif cur_kind == "action":
                doc["actions"].append(item)
            elif cur_kind == "qa" and "｜" in item:
                q, a = item.split("｜", 1)
                doc["qa"].append((strip_md(q), strip_md(a)))
            elif cur_kind == "body" and cur_node is not None and len(cur_node["points"]) < 3:
                p = strip_md(TS_PAT.sub("", item))
                if 6 <= len(p):
                    cur_node["points"].append(p[:60])
            continue
        if s.startswith(">") and cur_kind == "quote":
            q = s.lstrip("> ").strip()
            if q and not q.startswith("[!"):
                doc["quotes"].append(q)
    return doc


def fmt_inline(text, video_url):
    """行內：HTML 轉義＋時間碼變連結（僅 YouTube 可跳秒）。"""
    esc = html.escape(strip_md_link_keep(text))

    def sub(m):
        sec = ts_seconds(m)
        label = m.group(0)[1:-1]
        url = yt_ts(video_url, sec)
        if url:
            return f'<a class="ts" href="{html.escape(url)}" target="_blank" rel="noopener">{label}</a>'
        return f'<span class="ts flat">{label}</span>'
    return TS_PAT.sub(sub, esc)


def strip_md_link_keep(t):
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t or "")
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"[*_`]", "", t)
    return t.strip()


def yt_ts(video_url, sec):
    if not video_url or not ("youtube.com" in video_url or "youtu.be" in video_url):
        return None
    sep = "&" if "?" in video_url else "?"
    return f"{video_url}{sep}t={int(sec)}s"


BASE_CSS = r"""
@font-face{font-family:"AppSans";font-display:swap;src:local("Noto Sans TC"),local("思源黑體"),local("Microsoft JhengHei");}
@font-face{font-family:"AppSerif";font-display:swap;src:local("Noto Serif TC"),local("思源宋體"),local("Songti TC");}
:root{--navy:#1B2A4A;--deep:#13203A;--gold:#B8932E;--gold-2:#CCA53A;--paper:#E8E3D6;--dim:#9FB0C9;
  --card:#1F3050;--line:#2C4068;--green:#37C281;--red:#E0707A;
  --sans:"AppSans","Microsoft JhengHei",system-ui,sans-serif;--serif:"AppSerif","Noto Serif TC",serif;}
*{box-sizing:border-box}
body{margin:0;background:var(--deep);color:var(--paper);font-family:var(--sans);line-height:1.75;
  -webkit-font-smoothing:antialiased}
a{color:var(--gold-2)}
h1{font-family:var(--serif);text-wrap:balance}
.ts{font-size:.82em;font-weight:700;color:var(--gold-2);text-decoration:none;border-bottom:1px dashed var(--gold);
  padding:0 2px;white-space:nowrap}
.ts.flat{border-bottom:none;color:var(--dim)}
"""


# ---------------------------------------------------------------------------
# digest.html — 一頁精華卡（A4 可列印）
# ---------------------------------------------------------------------------
def build_digest(doc, meta, video_url):
    if not (doc["insights"] or doc["actions"]):
        return None
    ins = "".join(f'<li>{fmt_inline(x, video_url)}</li>' for x in doc["insights"][:8])
    act = "".join(f'<li><label><input type="checkbox"><span>{fmt_inline(x, video_url)}</span></label></li>'
                  for x in doc["actions"][:12])
    qts = "".join(f'<blockquote>{fmt_inline(q, video_url)}</blockquote>' for q in doc["quotes"][:4])
    bits = " · ".join(b for b in [html.escape(meta.get("channel") or ""),
                                  html.escape(meta.get("duration_str") or ""),
                                  html.escape(meta.get("upload_ymd") or "")] if b)
    link = (f'<a href="{html.escape(video_url)}" target="_blank" rel="noopener">▶ 原片</a>'
            if video_url else "")
    css = BASE_CSS + r"""
.page{max-width:820px;margin:0 auto;padding:34px 30px 60px}
header{border-bottom:3px double var(--gold);padding-bottom:14px;margin-bottom:22px}
h1{font-size:26px;margin:0 0 8px;color:#fff}
.meta{font-size:13px;color:var(--dim)}
h2{font-family:var(--serif);font-size:17px;color:var(--gold-2);margin:26px 0 10px;
  border-left:4px solid var(--gold);padding-left:10px}
ul{margin:0;padding-left:22px}
li{margin:7px 0;text-wrap:pretty}
.act ul{list-style:none;padding-left:2px}
.act label{display:flex;gap:9px;align-items:flex-start;cursor:pointer}
.act input{margin-top:7px;accent-color:var(--gold)}
blockquote{margin:10px 0;padding:10px 16px;background:var(--card);border-left:3px solid var(--gold);
  border-radius:0 8px 8px 0;font-family:var(--serif);font-size:15.5px}
footer{margin-top:34px;color:var(--dim);font-size:12px;border-top:1px solid var(--line);padding-top:12px}
.toolbar{position:fixed;top:14px;right:16px;display:flex;gap:8px}
.toolbar button{font-family:var(--sans);font-size:13px;font-weight:700;color:var(--deep);background:var(--gold);
  border:0;border-radius:8px;padding:7px 14px;cursor:pointer}
@media print{body{background:#fff;color:#1a1a1a}
  :root{--paper:#1a1a1a;--dim:#666;--card:#f4f1e8;--line:#ccc;--gold-2:#8a6d1c}
  h1{color:#1B2A4A}.toolbar{display:none}.page{max-width:none;padding:0}
  @page{size:A4;margin:16mm}}
"""
    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>精華卡｜{html.escape(doc['title'])}</title><style>{css}</style></head><body>
<div class="toolbar"><button onclick="print()">🖨 列印 / 存 PDF</button></div>
<div class="page">
<header><h1>{html.escape(doc['title'])}</h1><div class="meta">{bits}　{link}</div></header>
<h2>💡 重點洞察</h2><ul>{ins}</ul>
<div class="act"><h2>⚡ 帶得走的行動</h2><ul>{act}</ul></div>
{f'<h2>❝ 金句</h2>{qts}' if qts else ''}
<footer>一頁精華卡 · 由「影片轉文章」自動萃取自精讀文章 · 勾選行動項可列印追蹤</footer>
</div></body></html>"""


# ---------------------------------------------------------------------------
# mindmap.html — 大綱心智圖（純 CSS 樹 + <details> 摺疊，零依賴）
# ---------------------------------------------------------------------------
def build_mindmap(doc, video_url):
    if len(doc["tree"]) < 3:
        return None

    def node_label(n):
        t = html.escape(n["title"])
        if n.get("ts") is not None:
            url = yt_ts(video_url, n["ts"])
            tag = (f'<a class="ts" href="{html.escape(url)}" target="_blank" rel="noopener">{n["label"]}</a>'
                   if url else f'<span class="ts flat">{n["label"]}</span>')
            return f"{t} {tag}"
        return t

    branches = []
    for n in doc["tree"]:
        leaves = "".join(f'<li class="leaf">{node_label(c)}</li>' for c in n["children"][:8])
        if not leaves:
            leaves = "".join(f'<li class="leaf pt">{html.escape(p)}</li>' for p in n["points"])
        inner = f'<ul>{leaves}</ul>' if leaves else ""
        if inner:
            branches.append(f'<li><details open><summary>{node_label(n)}</summary>{inner}</details></li>')
        else:
            branches.append(f'<li><span class="lone">{node_label(n)}</span></li>')
    css = BASE_CSS + r"""
.wrap{max-width:1100px;margin:0 auto;padding:30px 26px 80px}
h1{font-size:22px;color:#fff;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:24px}
.map{display:flex;gap:0;align-items:flex-start}
.root{flex:0 0 190px;position:sticky;top:24px;background:var(--gold);color:var(--deep);font-weight:800;
  font-family:var(--serif);font-size:16px;padding:16px 14px;border-radius:14px;text-align:center;text-wrap:balance}
.tree{flex:1;list-style:none;margin:0;padding-left:34px}
.tree>li{position:relative;padding:5px 0 5px 22px}
.tree>li::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--line)}
.tree>li::after{content:"";position:absolute;left:0;top:1.35em;width:18px;height:2px;background:var(--line)}
.tree>li:first-child::before{top:1.35em}
.tree>li:last-child::before{bottom:auto;height:1.35em}
summary{cursor:pointer;font-weight:700;color:#fff;font-size:15.5px;list-style:none;display:inline-block;
  background:var(--card);border:1px solid var(--line);border-radius:10px;padding:7px 14px;text-wrap:balance}
summary::-webkit-details-marker{display:none}
details[open]>summary{border-color:var(--gold)}
.lone{display:inline-block;background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:7px 14px;font-weight:700;color:#fff;font-size:15.5px}
details ul{list-style:none;margin:6px 0 4px;padding-left:30px}
.leaf{position:relative;padding:3px 0 3px 18px;color:var(--paper);font-size:14px}
.leaf::before{content:"";position:absolute;left:0;top:.95em;width:12px;height:2px;background:var(--line)}
.leaf.pt{color:var(--dim)}
.ctrl{margin:0 0 16px;display:flex;gap:10px}
.ctrl button{font-family:var(--sans);font-size:12.5px;font-weight:700;color:var(--gold-2);background:transparent;
  border:1px solid var(--gold);border-radius:8px;padding:5px 12px;cursor:pointer}
"""
    js = ("function setAll(o){document.querySelectorAll('details').forEach(function(d){d.open=o});}")
    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>心智圖｜{html.escape(doc['title'])}</title><style>{css}</style></head><body>
<div class="wrap"><h1>🗺️ {html.escape(doc['title'])}</h1>
<div class="sub">章節大綱心智圖 · 點節點摺疊/展開 · 時間碼可點回原片</div>
<div class="ctrl"><button onclick="setAll(true)">全部展開</button><button onclick="setAll(false)">全部摺疊</button></div>
<div class="map"><div class="root">{html.escape(doc['title'])}</div>
<ul class="tree">{''.join(branches)}</ul></div></div>
<script>{js}</script></body></html>"""


# ---------------------------------------------------------------------------
# quiz.html — 自測翻牌卡（localStorage 記住掌握狀態）
# ---------------------------------------------------------------------------
def build_quiz(doc):
    if len(doc["qa"]) < 2:
        return None
    cards = []
    for i, (q, a) in enumerate(doc["qa"]):
        cards.append(
            f'<div class="fc" data-i="{i}"><div class="in">'
            f'<div class="face fr"><div class="tag">問題 {i + 1}</div><div class="tx">{html.escape(q)}</div>'
            f'<div class="hint">點卡片看答案</div></div>'
            f'<div class="face bk"><div class="tag">答案</div><div class="tx">{html.escape(a)}</div>'
            f'<div class="btns"><button class="ok" data-v="1">✓ 記住了</button>'
            f'<button class="ng" data-v="0">✗ 再複習</button></div></div>'
            f'</div></div>')
    css = BASE_CSS + r"""
.wrap{max-width:980px;margin:0 auto;padding:30px 24px 80px}
h1{font-size:22px;color:#fff;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:6px}
.stat{color:var(--gold-2);font-size:14px;font-weight:700;margin-bottom:18px}
.ctrl{display:flex;gap:10px;margin-bottom:18px}
.ctrl button{font-family:var(--sans);font-size:12.5px;font-weight:700;color:var(--gold-2);background:transparent;
  border:1px solid var(--gold);border-radius:8px;padding:5px 12px;cursor:pointer}
.ctrl button.on{background:var(--gold);color:var(--deep)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}
.fc{perspective:1100px;height:220px;cursor:pointer}
.fc .in{position:relative;width:100%;height:100%;transition:transform .5s;transform-style:preserve-3d}
.fc.flip .in{transform:rotateY(180deg)}
.face{position:absolute;inset:0;backface-visibility:hidden;background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:16px 18px;display:flex;flex-direction:column}
.face.bk{transform:rotateY(180deg);border-color:var(--gold)}
.tag{font-size:11.5px;font-weight:800;color:var(--gold-2);letter-spacing:1px;margin-bottom:8px}
.tx{flex:1;font-size:15px;line-height:1.65;overflow:auto;text-wrap:pretty}
.hint{font-size:12px;color:var(--dim)}
.btns{display:flex;gap:8px}
.btns button{flex:1;font-family:var(--sans);font-weight:700;font-size:13px;border:0;border-radius:8px;
  padding:8px 0;cursor:pointer}
.ok{background:var(--green);color:#08331f}.ng{background:var(--red);color:#3d0f14}
.fc.got .face{border-color:var(--green)}
.fc.got .fr .tag::after{content:"　✓ 已記住";color:var(--green)}
"""
    js = r"""
(function(){
var KEY='quiz:'+location.pathname;
var st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
var only=false;
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}}
function refresh(){
  var got=0,all=document.querySelectorAll('.fc');
  all.forEach(function(c){var i=c.getAttribute('data-i');
    var g=st[i]===1;c.classList.toggle('got',g);if(g)got++;
    c.style.display=(only&&g)?'none':'';});
  document.getElementById('stat').textContent='已記住 '+got+' / '+all.length+' 題';
}
document.querySelectorAll('.fc').forEach(function(c){
  c.addEventListener('click',function(e){
    if(e.target.tagName==='BUTTON'){
      st[c.getAttribute('data-i')]=+e.target.getAttribute('data-v');
      save();c.classList.remove('flip');refresh();return;}
    c.classList.toggle('flip');});
});
document.getElementById('only').addEventListener('click',function(){
  only=!only;this.classList.toggle('on',only);refresh();});
document.getElementById('reset').addEventListener('click',function(){
  st={};save();refresh();});
refresh();
})();
"""
    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>自測卡｜{html.escape(doc['title'])}</title><style>{css}</style></head><body>
<div class="wrap"><h1>🧠 {html.escape(doc['title'])}</h1>
<div class="sub">自我檢核翻牌卡 · 點卡片翻面 · 標記結果會記住（重開仍在）</div>
<div class="stat" id="stat"></div>
<div class="ctrl"><button id="only">只看還沒記住的</button><button id="reset">重設進度</button></div>
<div class="grid">{''.join(cards)}</div></div>
<script>{js}</script></body></html>"""


# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "reason": "USAGE", "message": '用法：derive_extras.py "<輸出夾>"'},
                         ensure_ascii=False))
        return 1
    folder = Path(sys.argv[1])
    art = folder / "article.md"
    if not art.exists():
        print(json.dumps({"ok": False, "reason": "NO_ARTICLE", "message": "夾內沒有 article.md"},
                         ensure_ascii=False))
        return 1
    doc = parse_article(art.read_text(encoding="utf-8"))
    meta = {}
    try:
        data = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
        meta = data.get("meta", {}) or {}
        up = str(meta.get("upload_date") or "")
        meta["upload_ymd"] = f"{up[0:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else ""
    except Exception:
        pass
    video_url = meta.get("webpage_url") or ""
    if not doc["title"]:
        doc["title"] = meta.get("title") or folder.name

    written, skipped = [], []
    for name, builder in (("digest.html", lambda: build_digest(doc, meta, video_url)),
                          ("mindmap.html", lambda: build_mindmap(doc, video_url)),
                          ("quiz.html", lambda: build_quiz(doc))):
        try:
            out = builder()
        except Exception as e:
            skipped.append(f"{name}:ERROR:{e}")
            continue
        if out:
            (folder / name).write_text(out, encoding="utf-8")
            written.append(name)
        else:
            skipped.append(f"{name}:no-source-section")
    print(json.dumps({"ok": True, "written": written, "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
