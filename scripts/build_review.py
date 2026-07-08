#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_review.py — 掃全庫 🧠 自我檢核卡，產獨立「每日回顧」review.html（間隔重複 SR）。

復用 build_index.scan()（已排除 private/殘骸）取全庫已完成文章 → 逐篇讀 article.md 抽
🧠 自我檢核 Q&A → 組出單檔 navy/gold review.html（卡片 JSON 內嵌、SR 引擎與 UI 純 JS、
離線 file:// 可用、零依賴）。SR 狀態存 localStorage['vtp-review']，跨 rebuild 依穩定
cardId 存活。

半衰期：soon=7d／later=14d／someday=28d；每場上限 20 張；回饋二元（記得/忘了）。

用法:
    python build_review.py [--base "桌面\\YT影片文章"]
"""
import argparse
import hashlib
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

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 讓 import build_index 成立
import build_index  # noqa: E402  復用 scan()（已排除 private/殘骸）
from common import resolve_base  # noqa: E402（知識庫 base 可設定：base_path.txt）


# ---------------------------------------------------------------------------
# Task 1: 卡片抽取
# ---------------------------------------------------------------------------
_QUIZ_H2 = re.compile(r"^##\s+.*(自我檢核|自我檢測|複習|測驗)", re.M)
_H2 = re.compile(r"^##\s+", re.M)
# 分隔優先序沿用 render_html.split_qa 的慣例（｜ || —— :: |）
_QA_SEPS = ("｜", "||", " —— ", "——", " :: ", "::", "|")


def _split_qa(item):
    for sep in _QA_SEPS:
        if sep in item:
            q, a = item.split(sep, 1)
            return q.strip(), a.strip()
    return item.strip(), ""


def extract_cards_from_md(md_text):
    """回傳 🧠 自我檢核區塊的 [(問題, 答案), ...]；無該區塊回 []。"""
    m = _QUIZ_H2.search(md_text)
    if not m:
        return []
    start = m.end()
    nxt = _H2.search(md_text, start)      # 下一個 h2 為區塊界
    block = md_text[start: nxt.start() if nxt else len(md_text)]
    cards = []
    for line in block.splitlines():
        s = line.strip()
        if not re.match(r"^[-*+]\s+", s):
            continue
        item = re.sub(r"^[-*+]\s+", "", s).strip()
        q, a = _split_qa(item)
        if q:
            cards.append((q, a))
    return cards


def card_id(href, q):
    """跨 rebuild 穩定：綁 href + normalize(問題)。問題被改＝新卡，舊狀態自然孤立、無害。"""
    key = href + "|" + re.sub(r"\s+", "", q).lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def harvest_cards(base):
    """掃全庫已完成文章的 🧠 卡；回傳 [{id,q,a,cat,title,href}, ...]。private/殘骸靠 scan() 已排除。"""
    base = Path(base)
    out = []
    for e in build_index.scan(base):
        if not e.get("done"):
            continue
        folder = base / os.path.dirname(e["href"])
        art = folder / "article.md"
        if not art.exists():
            continue
        try:
            md = art.read_text(encoding="utf-8")
        except Exception:
            continue
        for q, a in extract_cards_from_md(md):
            out.append({"id": card_id(e["href"], q), "q": q, "a": a,
                        "cat": e["category"], "title": e["title"], "href": e["href"]})
    return out


# ---------------------------------------------------------------------------
# Task 2: SR 半衰期引擎（純 JS，node 可單測；抽取靠下方標記）
# ---------------------------------------------------------------------------
SR_JS = r"""
// --SR_JS_START--
(function(){
  var HALFLIFE = {soon:7, later:14, someday:28}, DAY = 86400000;
  var PROMOTE = {"new":"soon", soon:"later", later:"someday", someday:"retired", retired:"retired"};
  function box(s){ return s && s.box ? s.box : "new"; }
  function isDue(s, now){
    if(!s) return true;
    if(s.box === "retired") return false;
    return (now - s.last) >= HALFLIFE[s.box]*DAY;
  }
  function p(s, now){
    if(!s) return 0;
    if(s.box === "retired") return 1;
    return Math.pow(2, -(now - s.last)/(HALFLIFE[s.box]*DAY));
  }
  function due(cards, states, now, cap){
    cap = cap || 20;
    var arr = cards.filter(function(c){ return isDue(states[c.id], now); });
    arr.sort(function(a,b){ return p(states[a.id], now) - p(states[b.id], now); });
    return arr.slice(0, cap);
  }
  function apply(s, remembered, now){
    var nb = remembered ? PROMOTE[box(s)] : "soon";
    var hist = (s && s.hist ? s.hist.slice() : []);
    hist.push({t: now, r: remembered?1:0});
    if(hist.length > 10) hist = hist.slice(-10);
    return {box: nb, last: now, hist: hist};
  }
  // 下批到期還有多久（天，向上取整）：非 retired 卡中最快到期者
  function nextDueDays(cards, states, now){
    var best = Infinity;
    for(var i=0;i<cards.length;i++){
      var s = states[cards[i].id];
      if(!s) return 0;                       // 有 new 卡＝今天就有
      if(s.box === "retired") continue;
      var remain = HALFLIFE[s.box]*DAY - (now - s.last);
      if(remain <= 0) return 0;
      if(remain < best) best = remain;
    }
    return best === Infinity ? -1 : Math.ceil(best/DAY);   // -1＝全 retired，無下批
  }
  var _api = {
    HALFLIFE:HALFLIFE, DAY:DAY, isDue:isDue, p:p, due:due, apply:apply, nextDueDays:nextDueDays
  };
  if(typeof window!=="undefined"){ window.SR = _api; } else { this.SR = _api; }
})();
// --SR_JS_END--
"""


# ---------------------------------------------------------------------------
# Task 3: review.html 組裝＋UI（navy/gold 單檔）
# ---------------------------------------------------------------------------
# @font-face + :root（含深色）沿用 render_html 的字型堆疊（永不含 PMingLiU）
CSS = r"""
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
  --radius:16px;--shadow:0 1px 2px rgba(16,42,67,.05),0 10px 30px rgba(16,42,67,.09);
}
:root[data-theme="dark"]{
  --navy:#a9c4ec;--navy-2:#88b0e0;--gold:#d9b85a;--gold-2:#e3c873;
  --ink:#e8eef6;--ink-2:#c4d0e0;--ink-3:#93a3b8;--line:#243244;
  --surface:#0f1722;--surface-2:#0b121b;--red:#e0707a;--green:#5cc69f;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.55);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--surface-2);color:var(--ink-2);
  font-family:var(--font-sans);font-size:17px;line-height:1.8;
  -webkit-font-smoothing:antialiased;min-height:100vh}

/* 頂部列 */
header.rv-top{background:var(--navy);color:#fff;padding:22px 0 18px}
:root[data-theme="dark"] header.rv-top{background:#0c1420}
header.rv-top .in{max-width:760px;margin:0 auto;padding:0 22px;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap}
header.rv-top h1{font-family:var(--font-serif);font-weight:900;font-size:22px;margin:0;color:#fff}
:root[data-theme="dark"] header.rv-top h1{color:#e8eef6}
header.rv-top .count{color:#d9b85a;font-size:14px;font-weight:700;margin-left:2px}
header.rv-top .grow{flex:1}
header.rv-top .tool{font-family:var(--font-sans);font-size:13.5px;font-weight:700;
  color:#dfe7f2;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.22);
  border-radius:20px;padding:6px 13px;cursor:pointer;text-decoration:none;transition:.15s}
header.rv-top .tool:hover{background:rgba(255,255,255,.20)}
/* 進度條 */
.rv-progress{height:4px;background:rgba(255,255,255,.18);border-radius:4px;
  margin:14px auto 0;max-width:760px;width:calc(100% - 44px);overflow:hidden}
.rv-progress > span{display:block;height:100%;width:0;
  background:linear-gradient(90deg,var(--gold),var(--gold-2));transition:width .25s ease}

.wrap{max-width:760px;margin:0 auto;padding:22px 22px 90px}

/* 分類 chip 列 */
.rv-chips{display:flex;gap:8px;flex-wrap:wrap;margin:2px 0 20px;align-items:center}
.rv-chip{font-family:var(--font-sans);font-size:13px;font-weight:700;color:var(--ink-3);
  background:var(--surface);border:1px solid var(--line);border-radius:20px;
  padding:6px 14px;cursor:pointer;transition:.15s}
.rv-chip:hover{border-color:var(--navy-2);color:var(--navy)}
.rv-chip.on{color:#fff;background:var(--navy);border-color:var(--navy)}
:root[data-theme="dark"] .rv-chip.on{color:#0b121b}
.rv-chip.all.on{background:var(--gold-2);border-color:var(--gold-2);color:#fff}
:root[data-theme="dark"] .rv-chip.all.on{color:#0b121b}
.rv-chip .cn{margin-left:6px;font-size:11px;opacity:.7}

/* 卡片（翻牌） */
.rv-stage{display:flex;justify-content:center;padding:8px 0 6px}
.rv-card{width:100%;max-width:640px;background:var(--surface);border:1px solid var(--line);
  border-top:4px solid var(--gold);border-radius:var(--radius);box-shadow:var(--shadow);
  padding:30px 30px 26px;min-height:260px;display:flex;flex-direction:column;
  cursor:pointer;transition:transform .12s,box-shadow .12s}
.rv-card:hover{transform:translateY(-2px)}
.rv-card .corner{display:flex;gap:8px 12px;align-items:center;flex-wrap:wrap;
  font-size:12px;color:var(--ink-3);margin-bottom:16px}
.rv-card .corner .tag{font-weight:700;color:var(--gold-2);background:var(--surface-2);
  border:1px solid var(--line);border-radius:16px;padding:2px 10px}
.rv-card .corner a{color:var(--navy-2);text-decoration:none;font-weight:700}
.rv-card .corner a:hover{text-decoration:underline}
.rv-card .q{font-family:var(--font-serif);font-weight:700;font-size:22px;line-height:1.55;
  color:var(--ink);text-wrap:balance;flex:0 0 auto}
.rv-card .a{margin-top:18px;padding-top:16px;border-top:1px dashed var(--line);
  font-size:16.5px;line-height:1.85;color:var(--ink-2);white-space:pre-wrap;
  display:none;animation:rvfade .22s ease}
.rv-card.flipped .a{display:block}
.rv-card .hint{margin-top:auto;padding-top:18px;font-size:12.5px;color:var(--ink-3);text-align:center}
.rv-card.flipped .hint{display:none}
@keyframes rvfade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}

/* 回饋鈕（翻牌後由 #rv-app.flipped 顯示） */
.rv-actions{display:none;gap:14px;justify-content:center;margin:20px auto 0;max-width:640px}
#rv-app.flipped .rv-actions{display:flex}
.rv-btn{font-family:var(--font-sans);font-size:16px;font-weight:800;flex:1;max-width:280px;
  border-radius:14px;padding:15px 10px;cursor:pointer;border:1.5px solid;transition:.15s}
.rv-btn small{display:block;font-size:11px;font-weight:700;opacity:.75;margin-top:2px}
.rv-btn.forget{color:var(--red);background:transparent;border-color:var(--red)}
.rv-btn.forget:hover{background:var(--red);color:#fff}
.rv-btn.remember{color:#fff;background:var(--green);border-color:var(--green)}
.rv-btn.remember:hover{filter:brightness(1.08)}

/* 空狀態 / 收尾頁 */
.rv-msg{max-width:560px;margin:40px auto;text-align:center;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:44px 30px}
.rv-msg .big{font-size:40px;line-height:1;margin-bottom:16px}
.rv-msg h2{font-family:var(--font-serif);font-weight:900;font-size:23px;color:var(--navy);margin:0 0 10px}
.rv-msg p{color:var(--ink-3);font-size:15px;margin:6px 0}
.rv-msg .stats{margin-top:18px;font-size:15px;color:var(--ink-2)}
.rv-msg .stats b.ok{color:var(--green)}
.rv-msg .stats b.no{color:var(--red)}
.rv-msg .again{margin-top:20px;font-family:var(--font-sans);font-size:14px;font-weight:800;
  color:#fff;background:var(--navy);border:none;border-radius:12px;padding:12px 22px;cursor:pointer}
:root[data-theme="dark"] .rv-msg .again{color:#0b121b;background:var(--navy)}
.rv-msg .home{display:inline-block;margin-top:14px;color:var(--gold-2);
  text-decoration:none;font-weight:700;font-size:14px}
.rv-msg .home:hover{text-decoration:underline}

footer{margin-top:44px;padding-top:16px;color:#9aa6b4;font-size:12px;text-align:center}
"""

THEME_INIT = """
(function(){try{var t=localStorage.getItem('vtp-theme');
if(!t){t=(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','light');}})();
"""

UI_JS = r"""
(function(){
  var LS = 'vtp-review';
  var NOW = Date.now();
  var root = document.documentElement;
  var app = document.getElementById('rv-app');
  var ALL = [];
  try { ALL = JSON.parse(document.getElementById('rv-data').textContent); } catch(e){ ALL = []; }
  var emptyLib = app.getAttribute('data-empty') === '1';
  var emptyHint = app.getAttribute('data-empty-hint') || '';

  function loadStates(){ try{ return JSON.parse(localStorage.getItem(LS)) || {}; }catch(e){ return {}; } }
  function saveStates(s){ try{ localStorage.setItem(LS, JSON.stringify(s)); }catch(e){} }
  var states = loadStates();

  // ---- 深色鈕 ----
  function themeIcon(){ var b=document.getElementById('rv-theme');
    if(b) b.textContent = (root.getAttribute('data-theme')==='dark') ? '☀ 淺色' : '🌙 深色'; }
  var tbtn = document.getElementById('rv-theme');
  if(tbtn) tbtn.addEventListener('click', function(){
    var t=(root.getAttribute('data-theme')==='dark')?'light':'dark';
    root.setAttribute('data-theme',t);
    try{ localStorage.setItem('vtp-theme',t); }catch(e){}
    themeIcon();
  });
  themeIcon();

  // ---- 狀態 ----
  var activeCat = '';        // '' = 全部分類
  var practiceAll = false;   // 「全部練習」忽略到期
  var queue = [], idx = 0, remembered = 0, forgot = 0;

  function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

  function pool(){
    if(!activeCat) return ALL;
    return ALL.filter(function(c){ return c.cat === activeCat; });
  }

  function buildQueue(){
    var cards = pool();
    if(practiceAll){
      // 練整庫（忽略到期），仍 new/低 p 優先
      queue = cards.slice().sort(function(a,b){
        return SR.p(states[a.id], NOW) - SR.p(states[b.id], NOW);
      }).slice(0, 20);
    } else {
      queue = SR.due(cards, states, NOW, 20);
    }
    idx = 0; remembered = 0; forgot = 0;
  }

  // ---- 頂部：到期數 + 新卡數 ----
  function dueSummary(){
    var cards = pool();
    var due = SR.due(cards, states, NOW, 100000);
    var news = due.filter(function(c){ return !states[c.id]; }).length;
    return { total: due.length, news: news };
  }
  function paintHeader(){
    var s = dueSummary();
    var cEl = document.getElementById('rv-count');
    if(practiceAll){
      cEl.textContent = '· 全部練習 · 共 ' + pool().length + ' 張';
    } else {
      cEl.textContent = '· 今日 ' + s.total + ' 張' + (s.news ? '（含 ' + s.news + ' 新卡）' : '');
    }
  }
  function paintProgress(){
    var bar = document.getElementById('rv-bar');
    var done = idx, total = queue.length || 1;
    bar.style.width = Math.min(100, Math.round(done/total*100)) + '%';
  }

  // ---- 分類 chip ----
  function paintChips(){
    [].forEach.call(document.querySelectorAll('.rv-chip.cat'), function(x){
      x.classList.toggle('on', !practiceAll && x.getAttribute('data-cat') === activeCat);
    });
    var allc = document.getElementById('rv-all');
    if(allc) allc.classList.toggle('on', practiceAll);
  }

  // ---- 卡片渲染 ----
  function renderCard(){
    app.classList.remove('flipped');
    var c = queue[idx];
    var href = esc(c.href), title = esc(c.title), cat = esc(c.cat);
    app.innerHTML =
      '<div class="rv-stage"><div class="rv-card" id="rv-card">' +
        '<div class="corner"><span class="tag">' + cat + '</span>' +
          '出自 <a href="' + href + '">《' + title + '》</a></div>' +
        '<div class="q">' + esc(c.q) + '</div>' +
        '<div class="a">' + (c.a ? esc(c.a) : '（這張卡沒有填答案）') + '</div>' +
        '<div class="hint">點卡片或按 <b>空白鍵</b> 看答案</div>' +
      '</div></div>' +
      '<div class="rv-actions">' +
        '<button class="rv-btn forget" id="rv-forget">✗ 忘了<small>1 / ←</small></button>' +
        '<button class="rv-btn remember" id="rv-remember">✓ 記得<small>2 / →</small></button>' +
      '</div>';
    var card = document.getElementById('rv-card');
    card.addEventListener('click', flip);
    document.getElementById('rv-forget').addEventListener('click', function(e){ e.stopPropagation(); grade(false); });
    document.getElementById('rv-remember').addEventListener('click', function(e){ e.stopPropagation(); grade(true); });
    paintProgress();
  }

  function flip(){
    var card = document.getElementById('rv-card');
    if(card){ card.classList.add('flipped'); app.classList.add('flipped'); }
  }
  function isFlipped(){
    var card = document.getElementById('rv-card');
    return card && card.classList.contains('flipped');
  }

  function grade(ok){
    if(!isFlipped()) return;          // 沒翻牌不計分
    var c = queue[idx];
    states[c.id] = SR.apply(states[c.id], ok, Date.now());
    saveStates(states);
    if(ok) remembered++; else forgot++;
    idx++;
    if(idx >= queue.length){ renderDone(); }
    else { renderCard(); }
    paintHeader();
  }

  // ---- 收尾頁 ----
  function renderDone(){
    paintProgress();
    var nd = SR.nextDueDays(pool(), states, Date.now());
    var next = (nd < 0) ? '全部卡片都已掌握 🏅' :
               (nd === 0 ? '還有卡片到期，可繼續' : '下一批到期在 ' + nd + ' 天後');
    app.innerHTML =
      '<div class="rv-msg"><div class="big">🎉</div>' +
      '<h2>今天回顧完成</h2>' +
      '<div class="stats">記得 <b class="ok">' + remembered + '</b> ／ 忘了 <b class="no">' + forgot + '</b></div>' +
      '<p>' + next + '</p>' +
      '<button class="again" id="rv-again">再練一輪（全部練習）</button><br>' +
      '<a class="home" href="index.html">← 回知識庫</a></div>';
    var ag = document.getElementById('rv-again');
    if(ag) ag.addEventListener('click', function(){ practiceAll = true; start(); });
  }

  // ---- 空狀態 ----
  function renderEmpty(){
    paintProgress();
    if(emptyLib){
      app.innerHTML = '<div class="rv-msg"><div class="big">📚</div>' +
        '<h2>還沒有自我檢核卡</h2><p>' + esc(emptyHint) + '</p>' +
        '<a class="home" href="index.html">← 回知識庫</a></div>';
      return;
    }
    var now = Date.now();
    var nd = SR.nextDueDays(pool(), states, now);
    // 下批將回浮的卡數＝pool 中尚未 retired 者（都會在某天再到期）
    var upcoming = pool().filter(function(c){
      var s = states[c.id]; return !s || s.box !== 'retired';
    }).length;
    var line = (nd < 0) ? '這個分類的卡都已掌握 🏅' :
               (nd === 0 ? '' : '下一批 ' + upcoming + ' 張在 ' + nd + ' 天後到期');
    app.innerHTML = '<div class="rv-msg"><div class="big">🎉</div>' +
      '<h2>今天沒有到期卡</h2>' +
      (line ? '<p>' + line + '</p>' : '') +
      '<p>或按下方「全部練習」複習整庫</p>' +
      '<button class="again" id="rv-again">全部練習</button><br>' +
      '<a class="home" href="index.html">← 回知識庫</a></div>';
    var ag = document.getElementById('rv-again');
    if(ag) ag.addEventListener('click', function(){ practiceAll = true; start(); });
  }

  // ---- 開場 ----
  function start(){
    buildQueue();
    paintHeader();
    paintChips();
    if(queue.length === 0){ renderEmpty(); }
    else { renderCard(); }
  }

  // ---- 分類 chip 事件 ----
  [].forEach.call(document.querySelectorAll('.rv-chip.cat'), function(ch){
    ch.addEventListener('click', function(){
      var c = ch.getAttribute('data-cat') || '';
      activeCat = (activeCat === c) ? '' : c;
      practiceAll = false;
      start();
    });
  });
  var allBtn = document.getElementById('rv-all');
  if(allBtn) allBtn.addEventListener('click', function(){
    practiceAll = !practiceAll;
    start();
  });

  // ---- 鍵盤 ----
  document.addEventListener('keydown', function(e){
    if(e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    var card = document.getElementById('rv-card');
    if(!card) return;
    if(e.code === 'Space'){ e.preventDefault(); if(!isFlipped()) flip(); return; }
    if(isFlipped()){
      if(e.key === '1' || e.key === 'ArrowLeft'){ e.preventDefault(); grade(false); }
      else if(e.key === '2' || e.key === 'ArrowRight'){ e.preventDefault(); grade(true); }
    }
  });

  start();
})();
"""


def build_page(cards):
    data = json.dumps(cards, ensure_ascii=False).replace("</", "<\\/")  # 防提早關閉 script
    n = len(cards)
    empty_hint = "知識庫還沒有自我檢核卡——先用技能做幾篇文章吧！" if n == 0 else ""
    # 分類 chip（依卡數）
    cat_counts = {}
    for c in cards:
        cat_counts[c["cat"]] = cat_counts.get(c["cat"], 0) + 1
    import html as _html
    cat_chips = "".join(
        f'<button class="rv-chip cat" data-cat="{_html.escape(cat)}">{_html.escape(cat)}'
        f'<span class="cn">{cnt}</span></button>'
        for cat, cnt in sorted(cat_counts.items()))
    chips = (f'<div class="rv-chips">{cat_chips}'
             f'<button class="rv-chip all" id="rv-all">🔁 全部練習</button></div>') if cat_chips else ""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日回顧 · 間隔重複</title>
<script>{THEME_INIT}</script>
<style>{CSS}</style></head>
<body>
<header class="rv-top"><div class="in">
  <h1>🧠 每日回顧</h1><span class="count" id="rv-count"></span>
  <span class="grow"></span>
  <button class="tool" id="rv-theme">🌙 深色</button>
  <a class="tool" href="index.html">← 回知識庫</a>
</div><div class="rv-progress"><span id="rv-bar"></span></div></header>
<div class="wrap">
{chips}
<div id="rv-app" data-empty="{'1' if n == 0 else '0'}" data-empty-hint="{_html.escape(empty_hint)}"></div>
</div>
<footer>間隔重複 · 半衰期 7／14／28 天 · 資料存本機瀏覽器 · 桌面「影片轉文章」自動整理</footer>
<script id="rv-data" type="application/json">{data}</script>
<script>{SR_JS}</script>
<script>{UI_JS}</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    default_base = resolve_base()
    ap.add_argument("--base", default=str(default_base))
    args = ap.parse_args()
    base = Path(args.base)
    base.mkdir(parents=True, exist_ok=True)
    cards = harvest_cards(base)
    out = base / "review.html"
    out.write_text(build_page(cards), encoding="utf-8")
    print(json.dumps({"ok": True, "total_cards": len(cards), "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
