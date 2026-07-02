#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_index.py — 掃描「桌面\\YT影片文章」，產出可搜尋的「知識總覽」首頁 index.html

把每支影片文章依「知識分類」資料夾歸類，做成一個 navy/gold 的知識庫入口：
  桌面\\YT影片文章\\<分類>\\<標題>__<id>\\article.html
直接放在 BASE 根目錄的 article 視為「未分類」。

v2（競品對標升級）：智慧檢視 chip（近7天/長文/快速讀/未完成）＋排序＋閱讀時間徽章＋
grid/list 切換＋衍生格式小連結（精華卡/心智圖/自測卡）＋偏好記憶(localStorage)＋
今日回顧輪播＋View Transitions 柔和重排。全部零依賴單檔。

用法:
    python build_index.py [--base "C:\\Users\\User\\Desktop\\YT影片文章"]
"""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8")
    except Exception:
        pass

SRC_MAP = {"manual": "人工字幕", "auto": "自動字幕", "auto-translated": "自動翻譯",
           "whisper": "語音辨識"}


def _platform(url):
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


def _dur_seconds(dur_str):
    try:
        parts = [int(p) for p in str(dur_str or "").split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
    except Exception:
        pass
    return 0


def load_entry(folder: Path, category: str, base: Path):
    tj = folder / "transcript.json"
    try:
        data = json.loads(tj.read_text(encoding="utf-8"))
    except Exception:
        return None
    meta = data.get("meta", {}) or {}
    track = data.get("track", {}) or {}
    has_article = (folder / "article.html").exists()
    target = (folder / "article.html") if has_article else tj
    rel = os.path.relpath(str(target), str(base)).replace("\\", "/")
    reldir = os.path.relpath(str(folder), str(base)).replace("\\", "/")
    up = str(meta.get("upload_date") or "")        # 防 upload_date 為 int 時 len() 炸

    # 抽出 article.md 內文純文字，供「全文搜尋」＋估閱讀時間（CJK 約 400 字/分）
    text, read_min = "", 0
    art = folder / "article.md"
    if art.exists():
        try:
            raw = art.read_text(encoding="utf-8")
            read_min = max(1, round(len(raw) / 400))
            raw = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)      # [文字](網址)→文字
            raw = re.sub(r"[#>*_`|~\-]", " ", raw)                  # 去 markdown 記號
            text = re.sub(r"\s+", " ", raw).strip()[:4000]
        except Exception:
            text = ""

    extras = {name: f"{reldir}/{fn}" for name, fn in
              (("digest", "digest.html"), ("mindmap", "mindmap.html"), ("quiz", "quiz.html"))
              if (folder / fn).exists()}

    return {
        "category": category,
        "title": meta.get("title") or folder.name,
        "channel": meta.get("channel") or "",
        "duration": meta.get("duration_str") or "",
        "dur_sec": _dur_seconds(meta.get("duration_str")),
        "source": track.get("source") or "",
        "url": meta.get("webpage_url") or "",
        "platform": _platform(meta.get("webpage_url")),
        "date": (f"{up[0:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else ""),
        "href": rel,
        "done": has_article,
        "mtime": folder.stat().st_mtime,
        "read_min": read_min,
        "extras": extras,
        "text": text,
    }


def scan(base: Path):
    entries = []
    if not base.exists():
        return entries
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "transcript.json").exists():
            # 影片夾直接在根目錄 → 未分類
            e = load_entry(child, "未分類", base)
            if e:
                entries.append(e)
        else:
            # 視為分類夾，掃其下的影片夾
            for sub in sorted(child.iterdir()):
                if sub.is_dir() and (sub / "transcript.json").exists():
                    e = load_entry(sub, child.name, base)
                    if e:
                        entries.append(e)
    return entries


CSS = r"""
@font-face{font-family:"AppSans";font-display:swap;src:local("Noto Sans TC"),local("思源黑體"),local("Microsoft JhengHei"),local("Microsoft YaHei");}
@font-face{font-family:"AppSerif";font-display:swap;src:local("Noto Serif TC"),local("思源宋體"),local("Songti TC");}
:root{--navy:#1B2A4A;--navy-2:#1e4d78;--gold:#B8932E;--gold-2:#b5740a;--ink:#102a43;--ink-3:#5b6b7f;
  --line:#dce4ed;--surface:#fff;--surface-2:#f4f8fc;--green:#0e7a5f;--radius:14px;
  --shadow:0 1px 2px rgba(16,42,67,.05),0 6px 18px rgba(16,42,67,.06);
  --font-sans:"AppSans","Microsoft JhengHei",system-ui,sans-serif;--font-serif:"AppSerif","Noto Serif TC",serif;}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-2);color:var(--ink);font-family:var(--font-sans);font-size:16px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px 100px}
header.top{background:var(--navy);color:#fff;padding:34px 0 30px;margin-bottom:26px}
header.top .in{max-width:1080px;margin:0 auto;padding:0 24px}
header.top h1{font-family:var(--font-serif);font-weight:900;font-size:30px;margin:0 0 6px;text-wrap:balance}
header.top .sub{color:#d9b85a;font-size:14px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:18px 0 8px}
#q{flex:1;min-width:200px;font-family:var(--font-sans);font-size:15px;padding:11px 14px;border:1px solid var(--line);
  border-radius:10px;background:var(--surface);color:var(--ink)}
#sort{font-family:var(--font-sans);font-size:13.5px;font-weight:700;color:var(--ink-3);padding:10px 8px;
  border:1px solid var(--line);border-radius:10px;background:var(--surface);cursor:pointer}
#view{font-size:15px;font-weight:700;color:var(--ink-3);background:var(--surface);border:1px solid var(--line);
  border-radius:10px;padding:9px 13px;cursor:pointer}
.stat{font-size:13.5px;color:var(--ink-3);width:100%}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:2px 0 6px}
.chip{font-family:var(--font-sans);font-size:13px;font-weight:700;color:var(--ink-3);background:var(--surface);
  border:1px solid var(--line);border-radius:20px;padding:5px 13px;cursor:pointer;transition:.15s}
.chip:hover{border-color:var(--navy-2);color:var(--navy)}
.chip.on{color:#fff;background:var(--navy);border-color:var(--navy)}
.chip.smart.on{background:var(--gold-2);border-color:var(--gold-2)}
.chip .cn{margin-left:6px;font-size:11px;opacity:.7}
.review{display:none;background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--gold);
  border-radius:10px;padding:10px 16px;margin:12px 0 4px;font-size:13.5px;color:var(--ink-3);box-shadow:var(--shadow)}
.review b{color:var(--navy)}
.review a{color:var(--gold-2);text-decoration:none;font-weight:700}
.review a:hover{text-decoration:underline}
.cat{margin:30px 0 0}
.cat h2{font-family:var(--font-serif);font-size:21px;font-weight:900;color:var(--navy);
  margin:0 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line)}
.cat h2::before{content:"";display:inline-block;width:8px;height:19px;background:var(--gold);
  border-radius:2px;margin-right:11px;vertical-align:-2px}
.cat h2 .n{font-family:var(--font-sans);font-size:13px;color:var(--gold-2);font-weight:700;margin-left:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
body.list .grid{grid-template-columns:1fr}
.card{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--gold);
  border-radius:12px;padding:15px 17px;box-shadow:var(--shadow);transition:.15s;cursor:pointer}
.card:hover{transform:translateY(-2px);border-top-color:var(--gold-2)}
body.list .card{border-top:1px solid var(--line);border-left:3px solid var(--gold)}
.card .t{font-family:var(--font-serif);font-weight:700;font-size:16.5px;line-height:1.4;margin-bottom:8px;text-wrap:balance}
.card .t a{color:var(--navy);text-decoration:none}
.card .m{font-size:12.5px;color:var(--ink-3);display:flex;gap:6px 12px;flex-wrap:wrap;align-items:center}
.badge{font-size:11px;font-weight:700;border-radius:20px;padding:1px 9px}
.badge.done{color:#fff;background:var(--green)}
.badge.pend{color:var(--gold-2);background:#fbf0dc;border:1px solid #ecdcae}
.extras{margin-top:9px;display:flex;gap:8px;flex-wrap:wrap}
.extras a{font-size:11.5px;font-weight:700;color:var(--navy-2);background:var(--surface-2);
  border:1px solid var(--line);border-radius:16px;padding:2px 10px;text-decoration:none;transition:.15s}
.extras a:hover{border-color:var(--gold);color:var(--gold-2)}
.empty{color:var(--ink-3);padding:40px 0;text-align:center}
footer{margin-top:50px;padding-top:18px;border-top:1px solid var(--line);color:#9aa6b4;font-size:12.5px;text-align:center}
"""

JS = r"""
(function(){
var LS='ytidx:';
function lsGet(k,d){try{return localStorage.getItem(LS+k)||d}catch(e){return d}}
function lsSet(k,v){try{localStorage.setItem(LS+k,v)}catch(e){}}
var q=document.getElementById('q');
var sortSel=document.getElementById('sort');
var viewBtn=document.getElementById('view');
var activeCat=lsGet('cat','');
var activeSmart=lsGet('smart','');
var NOW=Date.now()/1000;

function match(c){
  var v=(q.value||'').trim().toLowerCase();
  if(v&&(c.getAttribute('data-k')||'').indexOf(v)<0)return false;
  if(activeCat&&(c.getAttribute('data-cat')||'')!==activeCat)return false;
  var min=+c.getAttribute('data-min')||0,dt=+c.getAttribute('data-date')||0,done=c.getAttribute('data-done')==='1';
  if(activeSmart==='new'&&NOW-dt>7*86400)return false;
  if(activeSmart==='long'&&min<30)return false;
  if(activeSmart==='quick'&&(min>10||!done))return false;
  if(activeSmart==='todo'&&done)return false;
  return true;
}
function apply(){
  document.querySelectorAll('.card').forEach(function(c){c.style.display=match(c)?'':'none';});
  document.querySelectorAll('.cat').forEach(function(s){
    var any=[].some.call(s.querySelectorAll('.card'),function(c){return c.style.display!=='none';});
    s.style.display=any?'':'none';});
  var em=document.getElementById('empty2');
  if(em){var anyCard=[].some.call(document.querySelectorAll('.card'),function(c){return c.style.display!=='none';});
    em.style.display=anyCard?'none':'block';}
}
function sortCards(){
  var key=sortSel.value;
  document.querySelectorAll('.grid').forEach(function(g){
    var cards=[].slice.call(g.querySelectorAll('.card'));
    cards.sort(function(a,b){
      if(key==='new')return(+b.getAttribute('data-date'))-(+a.getAttribute('data-date'));
      if(key==='old')return(+a.getAttribute('data-date'))-(+b.getAttribute('data-date'));
      if(key==='dur')return(+b.getAttribute('data-dur'))-(+a.getAttribute('data-dur'));
      if(key==='min')return(+b.getAttribute('data-min'))-(+a.getAttribute('data-min'));
      return(a.getAttribute('data-t')||'').localeCompare(b.getAttribute('data-t')||'','zh-Hant');
    });
    cards.forEach(function(c){g.appendChild(c);});
  });
}
function rerender(fn){
  if(document.startViewTransition){document.startViewTransition(fn);}else{fn();}
}
if(q)q.addEventListener('input',function(){apply();});
if(sortSel){sortSel.value=lsGet('sort','new');sortCards();
  sortSel.addEventListener('change',function(){lsSet('sort',sortSel.value);rerender(sortCards);});}
function setView(v){document.body.classList.toggle('list',v==='list');
  if(viewBtn)viewBtn.textContent=(v==='list')?'⊞ 格狀':'☰ 列表';}
var view=lsGet('view','grid');setView(view);
if(viewBtn)viewBtn.addEventListener('click',function(){
  view=(view==='grid')?'list':'grid';lsSet('view',view);rerender(function(){setView(view);});});
function paintChips(){
  [].forEach.call(document.querySelectorAll('.chip.cat-c'),function(x){
    x.classList.toggle('on',activeCat!==''&&x.getAttribute('data-cat')===activeCat);});
  [].forEach.call(document.querySelectorAll('.chip.smart'),function(x){
    x.classList.toggle('on',activeSmart!==''&&x.getAttribute('data-smart')===activeSmart);});
}
[].forEach.call(document.querySelectorAll('.chip.cat-c'),function(ch){
  ch.addEventListener('click',function(){
    var c=ch.getAttribute('data-cat')||'';
    activeCat=(activeCat===c)?'':c;lsSet('cat',activeCat);
    rerender(function(){paintChips();apply();});
  });
});
[].forEach.call(document.querySelectorAll('.chip.smart'),function(ch){
  ch.addEventListener('click',function(){
    var s=ch.getAttribute('data-smart')||'';
    activeSmart=(activeSmart===s)?'':s;lsSet('smart',activeSmart);
    rerender(function(){paintChips();apply();});
  });
});
document.querySelectorAll('.card').forEach(function(c){
  c.addEventListener('click',function(e){
    if(e.target.closest('a'))return;
    var href=c.getAttribute('data-href');if(href)location.href=href;
  });
});
(function(){  // 今日回顧：隨機抽 2 篇已完成的舊文章，讓知識庫不變死庫
  var done=[].filter.call(document.querySelectorAll('.card'),function(c){return c.getAttribute('data-done')==='1';});
  if(done.length<3)return;
  var pick=[],used={};
  while(pick.length<2&&pick.length<done.length){
    var i=Math.floor(Math.random()*done.length);
    if(used[i])continue;used[i]=1;pick.push(done[i]);
  }
  var el=document.getElementById('review');
  if(!el)return;
  el.innerHTML='<b>🎲 溫故知新</b>　'+pick.map(function(c){
    return '<a href="'+c.getAttribute('data-href')+'">《'+(c.getAttribute('data-t')||'')+'》</a>';
  }).join('　·　');
  el.style.display='block';
})();
paintChips();apply();
})();
"""


def build_html(entries, base):
    # 依分類分組（未分類置底），分類內依資料夾修改時間新→舊
    cats = {}
    for e in entries:
        cats.setdefault(e["category"], []).append(e)
    names = sorted([c for c in cats if c != "未分類"]) + (["未分類"] if "未分類" in cats else [])

    total = len(entries)
    done = sum(1 for e in entries if e["done"])
    total_min = sum(e.get("read_min") or 0 for e in entries)
    sections = []
    extras_label = {"digest": "📄 精華卡", "mindmap": "🗺️ 心智圖", "quiz": "🧠 自測卡"}
    for cat in names:
        items = sorted(cats[cat], key=lambda x: x["mtime"], reverse=True)
        cards = []
        for e in items:
            badge = ('<span class="badge done">已完成</span>' if e["done"]
                     else '<span class="badge pend">逐字稿待寫</span>')
            src = SRC_MAP.get(e["source"], e["source"])
            meta_bits = [b for b in [
                html.escape(e["platform"]),
                html.escape(e["channel"]),
                html.escape(e["duration"]),
                (f"約 {e['read_min']} 分鐘讀完" if e.get("read_min") else ""),
                html.escape(e["date"]),
                html.escape(src) if src else "",
            ] if b]
            ex = "".join(f'<a href="{html.escape(href)}">{extras_label[k]}</a>'
                         for k, href in (e.get("extras") or {}).items())
            key = " ".join([e["title"], e["channel"], cat, e.get("text", "")]).lower()
            cards.append(
                f'<div class="card" data-href="{html.escape(e["href"])}" data-k="{html.escape(key)}" '
                f'data-cat="{html.escape(cat)}" data-date="{int(e["mtime"])}" data-dur="{e["dur_sec"]}" '
                f'data-min="{e.get("read_min") or 0}" data-done="{1 if e["done"] else 0}" '
                f'data-t="{html.escape(e["title"])}">'
                f'<div class="t"><a href="{html.escape(e["href"])}">{html.escape(e["title"])}</a></div>'
                f'<div class="m">{badge}<span>' + "</span><span>".join(meta_bits) + "</span></div>"
                + (f'<div class="extras">{ex}</div>' if ex else "") + "</div>"
            )
        sections.append(
            f'<section class="cat"><h2>{html.escape(cat)}<span class="n">{len(items)} 篇</span></h2>'
            f'<div class="grid">{"".join(cards)}</div></section>'
        )

    cat_chips = "".join(
        f'<button class="chip cat-c" data-cat="{html.escape(c)}">{html.escape(c)}'
        f'<span class="cn">{len(cats[c])}</span></button>' for c in names)
    smart_chips = (
        '<button class="chip smart" data-smart="new">🕐 近 7 天</button>'
        '<button class="chip smart" data-smart="long">📖 長文 &gt;30 分</button>'
        '<button class="chip smart" data-smart="quick">⚡ 10 分內讀完</button>'
        '<button class="chip smart" data-smart="todo">⏳ 待寫文章</button>')
    chip_html = f'<div class="chips">{smart_chips}{cat_chips}</div>' if names else ""

    body = "".join(sections) if sections else '<div class="empty">還沒有任何文章。用桌面的「影片轉文章」做第一篇吧！</div>'
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>我的影音知識庫</title>
<style>{CSS}</style></head><body>
<header class="top"><div class="in"><h1>📚 我的影音知識庫</h1>
<div class="sub">由 YouTube 影片與 Podcast 精讀而成的知識分類庫</div></div></header>
<div class="wrap">
<div class="bar"><input id="q" placeholder="🔎 搜尋標題／頻道／內文（全文搜尋）…">
<select id="sort"><option value="new">🕐 最新加入</option><option value="old">最舊優先</option>
<option value="dur">🎬 片長最長</option><option value="min">📖 閱讀最長</option><option value="t">🔤 標題</option></select>
<button id="view">☰ 列表</button>
<span class="stat">共 {total} 篇 · 已完成 {done} 篇 · {len(names)} 個分類 · 累計約 {total_min:,} 分鐘閱讀</span></div>
{chip_html}
<div class="review" id="review"></div>
{body}
<div class="empty" id="empty2" style="display:none">找不到符合的文章</div>
<footer>桌面「影片轉文章」自動整理 · 點卡片開啟精讀文章 · 卡片下方小膠囊開精華卡／心智圖／自測卡</footer>
</div>
<script>{JS}</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    default_base = Path(os.path.expanduser("~")) / "Desktop" / "YT影片文章"
    ap.add_argument("--base", default=str(default_base))
    args = ap.parse_args()
    base = Path(args.base)
    base.mkdir(parents=True, exist_ok=True)

    entries = scan(base)
    out = base / "index.html"
    out.write_text(build_html(entries, base), encoding="utf-8")
    print(json.dumps({"ok": True, "total": len(entries),
                      "done": sum(1 for e in entries if e["done"]),
                      "index": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
