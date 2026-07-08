#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch_document.py — 統一文檔進料口（P0-1）

把本機文檔（.pdf/.md/.txt/.docx）或網頁文章 URL 抽成與 fetch_transcript.py
同 schema 的 transcript.json / transcript.txt（meta.type="document"，schema v2），
後續寫文／渲染／入庫管線完全共用。

用法：
  python fetch_document.py <輸入1> [<輸入2> ...] [--merge] [--base DIR|--out DIR]
                           [--category 名] [--title 標題] [--private] [--date YYYYMMDD]
  python fetch_document.py --selftest

  - 輸入＝本機檔（.pdf/.md/.txt/.docx，允許帶引號）或 http(s) 網頁文章 URL，可混合。
  - 預設每輸入各產一夾；--merge 全部合併單一夾（transcript.txt 以【來源①：…】分節）。
  - 失敗→夾內 fetch_error.json＋stdout {ok:false, reason:…}
    reason ∈ FILE_NOT_FOUND / UNSUPPORTED_EXT / EXTRACT_EMPTY / URL_FETCH_FAILED / NEEDS_DEP

抽取器（不新裝套件）：pdf→pymupdf(fitz，已裝)；md/txt→直讀（編碼嘗試鏈）；
docx→stdlib zipfile+ElementTree；URL→trafilatura（有裝就用）否則 stdlib 退路。
"""

import argparse
import gzip
import hashlib
import html as html_mod
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SRC_MAP, safe_filename, resolve_base  # noqa: E402（P0-3 常數收斂：單一定義處）

DEFAULT_BASE = resolve_base()
DOC_EXTS = (".pdf", ".md", ".txt", ".docx")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class ExtractError(Exception):
    """抽取失敗（reason 對齊 fetch_transcript 的失敗契約）。"""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# 各型別抽取器：一律回 (text, title候選 or None)
# ---------------------------------------------------------------------------
def _clean_text(t):
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def read_text_best(path):
    """md/txt 直讀：utf-8 → utf-8-sig → cp950 → utf-16 嘗試鏈；全敗才 replace。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp950", "utf-16"):
        try:
            t = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\x00" in t:                       # 無 BOM 的 utf-16 誤判成 utf-8/cp950 會殘留 NUL
            continue
        return t.lstrip("﻿")
    log(f"[WARN] {Path(path).name} 編碼無法確定，以 utf-8 寬鬆解讀（壞字以 � 代）")
    return raw.decode("utf-8", errors="replace")


# Word/LibreOffice/PDF 匯出常見的預設垃圾標題（F4 擴充）：規範化後（去頭尾空白＋結尾數字、
# 不分大小寫）命中即判垃圾，退回檔名 stem。如「無題 1」「Untitled」「Document1」。
_JUNK_TITLES = frozenset((
    "untitled", "無題", "無標題", "未命名", "document", "文書", "新增文件", "blank",
))


def _bad_meta_title(s):
    """PDF metadata 標題守衛（F4）：疑似檔名／「Microsoft Word - 」匯出前綴／hash 樣
    （比照 fetch_transcript._looks_hashy）／預設垃圾標題（無題・Untitled・Document1…）
    → 棄用，讓標題退回檔名 stem。"""
    if re.search(r"(?i)\.(odt|docx?|rtf|pdf|txt|indd)$", s):
        return True
    if s.startswith("Microsoft Word - "):
        return True
    norm = re.sub(r"[\s\d]+$", "", s.strip()).strip().lower()   # 剝結尾數字/空白：Document1→document、無題 1→無題
    if norm in _JUNK_TITLES:
        return True
    return " " not in s and len(s) >= 18 and len(re.sub(r"[A-Za-z0-9_\-]", "", s)) == 0


def extract_pdf(path):
    try:
        import fitz  # pymupdf（本機已裝）
    except ImportError:
        raise ExtractError("NEEDS_DEP", "需要 pymupdf 讀 PDF：python -m pip install -U pymupdf")
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise ExtractError("EXTRACT_EMPTY", f"PDF 無法開啟：{e}")
    parts = []
    for i, page in enumerate(doc, 1):
        t = (page.get_text("text") or "").strip()
        if t:
            parts.append(f"【p.{i}】\n{t}")
    title = ((doc.metadata or {}).get("title") or "").strip() or None
    if title and _bad_meta_title(title):
        title = None                              # F4：壞 metadata 標題 → extract_one 退回 p.stem
    doc.close()
    return "\n\n".join(parts), title


def extract_md(path):
    text = read_text_best(path)
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)   # 首個一級標題當標題候選
    return text, (m.group(1).strip() if m else None)


def extract_txt(path):
    return read_text_best(path), None


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"


def extract_docx(path):
    import zipfile
    from xml.etree import ElementTree as ET
    try:
        with zipfile.ZipFile(str(path)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
            title = None
            try:                                  # 核心屬性 dc:title（沒有就算了）
                cel = ET.fromstring(z.read("docProps/core.xml")).find(_DC_NS + "title")
                if cel is not None and (cel.text or "").strip():
                    title = cel.text.strip()
            except (KeyError, ET.ParseError):
                pass
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ExtractError("EXTRACT_EMPTY", f"docx 無法解析：{e}")
    paras = []
    for p in root.iter(_W_NS + "p"):              # </w:p> 斷段
        s = "".join(t.text or "" for t in p.iter(_W_NS + "t")).strip()
        if s:
            paras.append(s)
    return "\n\n".join(paras), title


def fetch_url_html(url):
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = (resp.headers.get_content_type() or "").lower() \
                if resp.headers.get("Content-Type") else ""
            if ctype and ctype not in ("text/html", "application/xhtml+xml"):   # F5
                raise ExtractError("URL_FETCH_FAILED",
                                   f"非 HTML 內容（{ctype}；PDF 等文檔請下載後以檔路徑進料）：{url}")
            raw = resp.read()
            charset = resp.headers.get_content_charset()
    except ExtractError:
        raise
    except Exception as e:
        raise ExtractError("URL_FETCH_FAILED", f"網頁抓取失敗：{e}")
    if raw[:2] == b"\x1f\x8b":                    # 少數伺服器不看 Accept-Encoding 硬回 gzip
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    if not charset:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096], re.I)
        charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _html_title(h):
    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    if not m:
        return None
    t = html_mod.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return t or None


def _strip_tags_to_text(fragment):
    t = re.sub(r"(?is)<(?:br|/p|/div|/li|/h[1-6]|/tr|/blockquote|/section)[^>]*>", "\n", fragment)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html_mod.unescape(t)
    t = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in t.split("\n"))
    return _clean_text(t)


def _html_fallback_extract(h):
    """stdlib 退路：去 script/style/nav/header/footer，優先 <article>，
    再優先 <p> 集合，最後整個 body 去標籤。"""
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    for tag in ("script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form"):
        h = re.sub(rf"(?is)<{tag}\b.*?</{tag}>", " ", h)
    arts = re.findall(r"(?is)<article\b.*?</article>", h)
    scope = max(arts, key=len) if arts else None
    if scope is None:
        m = re.search(r"(?is)<body\b.*?</body>", h)
        scope = m.group(0) if m else h
    ps = [_strip_tags_to_text(p) for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", scope)]
    ps = [p for p in ps if len(p) > 1]
    if sum(len(p) for p in ps) > 200:             # 段落夠多 → 用段落集合（保段落）
        return "\n\n".join(ps)
    return _strip_tags_to_text(scope)             # 否則整塊去標籤（paulgraham 式 <br> 排版）


def extract_url(url):
    h = fetch_url_html(url)
    title = _html_title(h)
    text = None
    try:
        import trafilatura                        # 有裝就用（不強制安裝）
        try:
            text = trafilatura.extract(h, url=url, include_comments=False)
        except Exception as e:
            log(f"[WARN] trafilatura 抽取失敗（{e}）→ 改用內建退路")
    except ImportError:
        pass
    if not (text or "").strip():
        text = _html_fallback_extract(h)
    if not (text or "").strip():
        raise ExtractError("EXTRACT_EMPTY", f"網頁抽不出正文：{url}")
    return _clean_text(text), title


# ---------------------------------------------------------------------------
# 單一輸入 → 抽取結果 dict
# ---------------------------------------------------------------------------
def _strip_quotes(s):
    return (s or "").strip().strip('"').strip("'").strip()


def extract_one(raw_input):
    """回 dict(source/url/text/title/date/seed/display)；失敗丟 ExtractError。"""
    s = _strip_quotes(raw_input)
    if re.match(r"(?i)^https?://", s):
        log(f"[抽取] 網頁：{s}")
        text, title = extract_url(s)
        return {
            "source": "web", "url": s, "text": text,
            "title": title or s,
            "date": date.today().strftime("%Y%m%d"),
            "seed": hashlib.sha1(s.encode("utf-8")).hexdigest(),
            "display": s,
        }
    p = Path(s)
    if not p.is_file():
        raise ExtractError("FILE_NOT_FOUND", f"找不到檔案：{s}")
    ext = p.suffix.lower()
    if ext not in DOC_EXTS:
        raise ExtractError("UNSUPPORTED_EXT",
                           f"不支援的副檔名 {ext or '(無)'}（限 pdf/md/txt/docx）：{p.name}")
    log(f"[抽取] {ext.lstrip('.')}：{p}")
    extractor = {".pdf": extract_pdf, ".md": extract_md,
                 ".txt": extract_txt, ".docx": extract_docx}[ext]
    text, title = extractor(p)
    text = _clean_text(text)
    if not text:
        raise ExtractError("EXTRACT_EMPTY", f"抽不出任何文字：{p.name}")
    return {
        "source": ext.lstrip("."), "url": "", "text": text,
        "title": title or p.stem,
        "date": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y%m%d"),
        "seed": hashlib.sha1(p.read_bytes()).hexdigest(),
        "display": str(p),
    }


# ---------------------------------------------------------------------------
# 輸出契約（對齊 fetch_transcript）
# ---------------------------------------------------------------------------
def emit(outdir, ident, title, source, text, url, date_str, private, display_src, sources=None):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    char_count = len(text)
    meta = {
        "type": "document",                       # schema v2（P0-2）
        "id": ident,                              # doc-<sha1前8>
        "title": title,
        "channel": "",
        "upload_date": date_str,
        "duration": 0,
        "duration_str": "",
        "webpage_url": url or "",
        "language": "",
        "description": "",
    }
    if private:
        meta["private"] = True                    # 敏感分流（P0-4）：build_index 整篇跳過
    out_json = {
        "ok": True,
        "meta": meta,
        "chapters": [],
        "track": {"source": source, "char_count": char_count},
        "segments": [],
    }
    if sources is not None:                        # 選配頂層 key；單源/av 無此鍵→下游短路、位元組不變
        out_json["sources"] = sources
    (outdir / "transcript.json").write_text(
        json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")
    try:                                          # 前次失敗殘留的 fetch_error.json：成功即清掉
        (outdir / "fetch_error.json").unlink()
    except OSError:
        pass
    label = SRC_MAP.get(source, source)
    lines = [
        f"標題：{title}",
        f"來源：{display_src}",
        f"類型：{label}　約 {char_count:,} 字",
        "=" * 60,
        "",
        text,
    ]
    (outdir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    log(f"[完成] {title}（{label}，{char_count:,} 字）")
    log(f"      → {outdir / 'transcript.json'}")
    log(f"      → {outdir / 'transcript.txt'}")
    # stdout 機器可讀小結（格式對齊 fetch_transcript，launcher 據此解析）
    print(json.dumps({
        "ok": True,
        "out_dir": str(outdir),
        "title": title,
        "source": source,
        "char_count": char_count,
    }, ensure_ascii=False))


def fail(outdir, reason, message):
    if outdir is not None:
        try:
            outdir = Path(outdir)
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "fetch_error.json").write_text(
                json.dumps({"ok": False, "reason": reason, "message": message},
                           ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    print(json.dumps({"ok": False, "reason": reason, "message": message}, ensure_ascii=False))
    log(f"[ERROR] {message}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _err_title(raw, args_title):
    if args_title:
        return args_title
    s = _strip_quotes(raw)
    return s if re.match(r"(?i)^https?://", s) else (Path(s).stem or "文檔")


def run(args):
    base = Path(args.base) if args.base else DEFAULT_BASE
    if args.category:
        base = base / safe_filename(args.category)
    fixed_out = Path(args.out) if args.out else None
    if fixed_out and not args.merge and len(args.inputs) > 1:
        log("[WARN] --out 搭配多輸入且未 --merge → 改當 base 用（各輸入各產一夾）")
        base, fixed_out = fixed_out, None

    if args.merge:
        try:
            items = [extract_one(r) for r in args.inputs]
        except ExtractError as e:
            seed = hashlib.sha1("|".join(args.inputs).encode("utf-8")).hexdigest()
            t = _err_title(args.inputs[0], args.title)
            outdir = fixed_out or base / f"{safe_filename(t)}__doc-{seed[:8]}"
            fail(outdir, e.reason, e.message)
            return 2
        title = args.title or (items[0]["title"] if len(items) == 1
                               else f"{items[0]['title']} 等{len(items)}份")
        source = items[0]["source"] if len({it["source"] for it in items}) == 1 else "mixed"
        ident = "doc-" + hashlib.sha1(
            "|".join(it["seed"] for it in items).encode("utf-8")).hexdigest()[:8]
        parts, sources = [], []
        for i, it in enumerate(items):
            mark = CIRCLED[i] if i < len(CIRCLED) else str(i + 1)
            parts.append(f"【來源{mark}：{it['title']}】\n\n{it['text']}")
            sources.append({                          # 同迴圈累積結構化來源（供 render 端錨點＋附錄）
                "n": i + 1, "mark": mark, "title": it["title"],
                "source": it["source"], "url": it["url"],
                "display": it["display"], "text": it["text"],
            })
        text = "\n\n\n".join(parts)
        url = items[0]["url"] if len(items) == 1 else ""   # 多來源不造單一連結（防假連結雷）
        outdir = fixed_out or base / f"{safe_filename(title)}__{ident}"
        emit(outdir, ident, title, source, text, url, args.date or items[0]["date"],
             args.private, "；".join(it["display"] for it in items), sources=sources)
        return 0

    rc = 0
    for raw in args.inputs:
        try:
            it = extract_one(raw)
        except ExtractError as e:
            s = _strip_quotes(raw)
            seed = hashlib.sha1(s.encode("utf-8")).hexdigest()
            t = _err_title(raw, args.title)
            outdir = fixed_out if (fixed_out and len(args.inputs) == 1) \
                else base / f"{safe_filename(t)}__doc-{seed[:8]}"
            fail(outdir, e.reason, e.message)
            rc = 2
            continue
        title = args.title or it["title"]
        ident = "doc-" + it["seed"][:8]
        outdir = fixed_out if (fixed_out and len(args.inputs) == 1) \
            else base / f"{safe_filename(title)}__{ident}"
        emit(outdir, ident, title, it["source"], it["text"], it["url"],
             args.date or it["date"], args.private, it["display"])
    return rc


# ---------------------------------------------------------------------------
# --selftest：自產暫存 md＋最小 docx 跑一輪自驗
# ---------------------------------------------------------------------------
def make_min_docx(path, title, paragraphs):
    """最小可讀 docx（給 --selftest 與外部測試用）。"""
    import zipfile
    body = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{html_mod.escape(p)}</w:t></w:r></w:p>"
        for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{html_mod.escape(title)}</dc:title></cp:coreProperties>")
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/word/document.xml" ContentType='
              '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType='
              '"application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument'
            '/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006'
            '/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("docProps/core.xml", core)


def selftest():
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="fetchdoc_st_"))
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))
        log(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    try:
        md = tmp / "自測文件.md"
        md.write_text("# 自測標題\n\n第一段內容。\n\n第二段內容。", encoding="utf-8")
        dx = tmp / "自測文件.docx"
        make_min_docx(dx, "Docx自測標題", ["Docx 第一段", "Docx 第二段"])

        out1 = tmp / "out_md"
        rc1 = run(argparse.Namespace(inputs=[str(md)], merge=False, base=None, out=str(out1),
                                     category=None, title=None, private=True, date="20260101"))
        j1 = json.loads((out1 / "transcript.json").read_text(encoding="utf-8"))
        check("md 單檔 rc=0", rc1 == 0)
        check("meta.type=document", j1["meta"]["type"] == "document")
        check("標題取 md 首個 #", j1["meta"]["title"] == "自測標題")
        check("meta.private=true", j1["meta"].get("private") is True)
        check("--date 生效", j1["meta"]["upload_date"] == "20260101")
        check("track.source=md", j1["track"]["source"] == "md")

        out2 = tmp / "out_merge"
        rc2 = run(argparse.Namespace(inputs=[str(md), str(dx)], merge=True, base=None,
                                     out=str(out2), category=None, title="自測合併",
                                     private=False, date=None))
        j2 = json.loads((out2 / "transcript.json").read_text(encoding="utf-8"))
        t2 = (out2 / "transcript.txt").read_text(encoding="utf-8")
        check("merge rc=0", rc2 == 0)
        check("merge 混類 source=mixed", j2["track"]["source"] == "mixed")
        check("merge 標題=--title", j2["meta"]["title"] == "自測合併")
        check("txt 有來源①②標頭", "【來源①：" in t2 and "【來源②：" in t2)
        check("docx 段落抽出", "Docx 第一段" in t2 and "Docx 第二段" in t2)
        check("docx 標題取核心屬性", "【來源②：Docx自測標題】" in t2)
    finally:
        allok = all(c for _, c in results)
        print(json.dumps({"ok": allok, "selftest": {n: c for n, c in results}},
                         ensure_ascii=False))
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if allok else 2


def main():
    for _s in (sys.stdout, sys.stderr):           # cp950 主控台防線（同 launcher 慣例）
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="文檔進料口：PDF/網頁文章/md/txt/docx → transcript.json（schema v2）")
    ap.add_argument("inputs", nargs="*", help="本機檔路徑或 http(s) 網頁文章 URL，可混合多個")
    ap.add_argument("--merge", action="store_true", help="全部輸入合併成單一夾（【來源①：…】分節）")
    ap.add_argument("--base", default=None, help="輸出基底夾（預設 桌面\\YT影片文章）")
    ap.add_argument("--out", default=None, help="直接指定輸出夾（單輸入或 --merge 時）")
    ap.add_argument("--category", default=None, help="知識分類：輸出到 base\\分類\\")
    ap.add_argument("--title", default=None, help="覆蓋標題（--merge 時為合併標題）")
    ap.add_argument("--private", action="store_true", help="敏感內容：meta.private=true，不入知識總覽")
    ap.add_argument("--date", default=None, help="覆蓋 upload_date（YYYYMMDD）")
    ap.add_argument("--selftest", action="store_true", help="自產暫存 md＋最小 docx 跑一輪自驗")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.inputs:
        ap.error("至少要給一個輸入（檔路徑或 URL），或用 --selftest")
    if args.date:
        d = args.date.replace("-", "")
        if not re.fullmatch(r"\d{8}", d):
            ap.error(f"--date 需為 YYYYMMDD：{args.date}")
        args.date = d
    sys.exit(run(args))


if __name__ == "__main__":
    main()
