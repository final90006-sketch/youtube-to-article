---
name: 影片轉文章
description: >-
  在本機 Windows 把 YouTube 影片或 Podcast（Apple Podcasts／SoundCloud／Firstory／SoundOn／節目 RSS／直接的 .mp3…）
  轉成「可閱讀的詳盡長文」：用 yt-dlp 抓最高保真字幕（人工＞原語自動＞翻譯）＋章節＋中繼資料；
  Podcast 通常無字幕→自動下載音訊用 Whisper 語音辨識（有 NVIDIA GPU 自動加速），再由 Claude 依「逐節精讀」鐵則
  整理成一篇忠實、保留所有細節、可當文章讀完整部影片／整集 Podcast 的繁體中文文章（非三行摘要），
  輸出 article.md 與 navy/gold 大字宋體閱讀版 article.html（YouTube 時間碼可點回原片該秒）。
  **每當使用者貼 YouTube 連結或 Podcast 連結（Apple Podcasts／SoundCloud／Firstory／SoundOn／節目 RSS／.mp3）
  要摘要／重點／看不完聽不完／太長／幫我看這部影片或這集 Podcast／把影片或 Podcast 做成文章／要逐字稿或詳細內容／
  說 Journal 之類摘要太短想看細節，務必使用本技能**——即使只丟一個連結沒明講格式，也主動套用。
  Spotify 因 DRM 無法擷取（腳本會回明確指引，請改貼同一集的 Apple Podcasts／RSS／YouTube 連結）。
  不適用於：寫情報專報、簡報投影片、本機影片／音檔（非網路連結）。
---

# 影片轉文章｜YouTube／Podcast → 可閱讀的詳盡長文（Windows 本機）

把一部 YouTube 影片、或一集 Podcast，變成一篇**讀完就等於看完整部影片／聽完整集**的繁體中文文章。
解決使用者的兩個痛點：①影片／節目太長、沒時間看或聽；②一般 AI 摘要**太短、把細節摘掉了**。
本技能的立場是 **「精讀」而非「摘要」**——寧長毋短、寧詳毋略，只要是影片／節目講過的實質內容都要留下。

**交付物**：在 `桌面\YT影片文章\[<知識分類>\]<標題>__<id>\` 夾內產出（有分類時多一層分類夾）
- `article.md` —— 文章原稿（給人編輯／再利用）
- `article.html` —— **精緻權威閱讀版**（navy/gold、思源宋體標題＋思源黑體內文、離線也好看；含章節導覽側欄、重點洞察卡、可勾選的「帶得走行動」、金句卡、頂部工具列：複製全文／匯出 Markdown／列印·存 PDF／深色模式；時間碼與逐字稿可點回原片）
- `transcript.json` / `transcript.txt` —— 原始逐字字幕（佐證與覆核用）

## 何時用 / 不適用
- **用**：使用者貼 YouTube **或 Podcast** 網址並想「摘要／重點／看不完聽不完／太長／做成文章／看細節／逐字稿」。只給連結＝預設動工。
- **支援的來源**（皆由 `fetch_transcript.py` 統一處理）：
  - YouTube／X(Twitter)／Vimeo 等 yt-dlp 支援的影片站（有字幕用字幕、無字幕用語音辨識）。
  - **Apple Podcasts**（請給「單集」連結，含 `?i=<id>`）、**SoundCloud**（單曲/單集連結）。
  - **Firstory**（單集頁 `open.firstory.me/story/<id>`）、**SoundOn**（單集頁 `player.soundon.fm/p/<id>/episodes/<id>`）：腳本會自動轉成節目 RSS 並**精準對到使用者貼的那一集**。
  - 任何 **Podcast RSS／訂閱源（.xml）** 或 **直接的 .mp3** 連結。貼 RSS 時預設取**最新一集**，要指定第幾集加 `--episode N`（1=最新）。
- **不適用**：
  - **Spotify**：音訊受 DRM 保護、yt-dlp 無法擷取——腳本會回 `SPOTIFY_DRM` 並指引「改貼同一集的 Apple Podcasts／RSS／YouTube 連結」。
  - 寫情報專報、要做簡報、本機影片／音檔（非網路連結）。

## 環境前置（一次性）
- 需要 `python 3`、`yt-dlp`、`ffmpeg`（安裝方式見同資料夾 `README.md`）。Podcast／無字幕影片會用 `faster-whisper` 語音辨識（可選）。
- **無需** API 金鑰——文章由當前 Claude（你這個 Claude Code session）直接撰寫。
- 指令中的 `<技能資料夾>` = 本技能安裝位置（通常 `你的使用者資料夾\.claude\skills\影片轉文章\`）；Claude 執行時請換成實際絕對路徑。輸出預設在 `桌面\YT影片文章\`。
- **知識庫位置可設定**：技能根的 `base_path.txt`（單行路徑）＝知識庫 base；四腳本與桌面啟動器都讀它，搬動知識庫只需改這一檔。無此檔時退回預設 `桌面\YT影片文章`（公開 repo 相容）。`--base` 顯式參數仍優先於本設定。

---

## 流程（三步，外科手術式、別加戲）

### 第 1 步：抓字幕／音訊＋中繼資料
```
python "<技能資料夾>\scripts\fetch_transcript.py" "<影片或 Podcast 網址>" --base "桌面\YT影片文章"
```
- 腳本會自動：選最佳字幕（**人工 ＞ 原語自動 ＞ 自動翻譯**，原語優先以求保真，翻譯交給你做）、抓章節、建立可讀資料夾，輸出 `transcript.json`＋`transcript.txt`。
- **若目標夾已有 `transcript.json`（例如由桌面啟動器先抓好）：跳過本步，直接讀它進第 2 步**，不要重抓。
- 讀 stdout 的 JSON 小結：確認 `source`（manual/auto/auto-translated/**whisper**）、`lang`、`chapters`、`char_count`。**把 out_dir 記下，後續都在這夾作業。**
- **要指定語言**時加 `--lang zh-Hant`（或 `en`/`ja`…）。預設不用加。
- **無字幕自動備援（＝Podcast 的常態）**：沒有任何字幕時，腳本會**自動下載音訊並用 Whisper 語音辨識**（`source=whisper`），產出一樣的 transcript.json。有 NVIDIA GPU 自動加速；長片／長集在 CPU 上較慢（會印辨識進度）。可調品質：`--whisper-model tiny/base/small(預設)/medium/large-v3`；要關閉用 `--no-whisper`；要強制辨識用 `--whisper`。
- **Podcast 連結處理（腳本內建，無須你手動轉）**：
  - **Apple Podcasts／SoundCloud／直接 .mp3**：直接吃，免處理。Apple 請用「單集」連結（含 `?i=`）。
  - **Firstory `story/`、SoundOn `player/` 單集頁**：腳本會自動轉成節目 RSS 並**精準對到那一集**（用頁面/URL 內的 id 比對 feed），標題也用 RSS 真標題。
  - **節目 RSS／訂閱源（.xml）**：是「整包多集清單」，腳本預設取**最新一集**；要指定第幾集加 `--episode N`（1=最新）。
  - **Spotify**：DRM 無法擷取，會回 `SPOTIFY_DRM`，請改貼 Apple／RSS／YouTube 連結。
- **失敗處理**（腳本會回明確 reason，不杜撰）：
  - `NEEDS_WHISPER`：缺語音辨識套件 → 請使用者執行 `python -m pip install -U faster-whisper`（本機已裝則不會出現）。
  - `AUDIO_FAILED` / `ASR_EMPTY`：音訊抓不到或整片無語音 → 照訊息回報。
  - `NO_SUBTITLES`：僅在加了 `--no-whisper` 時出現。
  - `SPOTIFY_DRM`：Spotify 受 DRM 保護無法擷取 → 請使用者改貼同一集的 Apple Podcasts／RSS／YouTube 連結。
  - `FIRSTORY_PAGE`：Firstory 單集頁無法自動對應到 RSS → 請改貼該集 Apple／RSS／YouTube 連結。
  - `UNSUPPORTED`：連結 yt-dlp 不支援 → 若是 Podcast 請改貼單集連結（Apple `?i=`／.mp3／節目 RSS）。
  - `NO_EPISODES`：RSS 訂閱源裡沒有任何單集。
  - `VIDEO_UNAVAILABLE / PRIVATE / MEMBERS_ONLY / AGE_RESTRICTED`：照訊息回報，請使用者換連結或提供可存取方式。

### 第 2 步：寫文章（本技能的核心，見下方「撰寫鐵則」）
- 讀 `transcript.json`（有時間碼、章節、逐段文字）與 `transcript.txt`（人可讀）。
- 依「撰寫鐵則」把整部影片／整集 Podcast 整理成 `article.md`，存進同一夾。
- **Podcast（`source=whisper`）**：下方鐵則的「影片」一律可讀作「這集節目」；文中用「本集／節目中提到」較自然，且因內容由語音辨識而來，**務必**在文章開頭用一句 `> [!warn]` 註明「本集無字幕，內容由語音辨識產生，可能有錯字／斷句誤差」。
- **長影片／長集（逐字 > 約 6000 字／詞）必須分段寫、分次寫進檔案**：以章節（或每 8–12 分鐘）為單位，一節一節 append 進 `article.md`，**嚴禁中途用「（後略）」「以下省略」草草收尾**。寧可多次寫入也要寫完整部。

### 第 3 步：渲染閱讀版、更新知識總覽、打開
```
python "<技能資料夾>\scripts\render_html.py" --md "<夾>\article.md" --json "<夾>\transcript.json" --out "<夾>\article.html"
python "<技能資料夾>\scripts\build_index.py"
python "<技能資料夾>\scripts\build_review.py"
```
然後用 `start "" "<夾>\article.html"`（PowerShell）打開給使用者看，並在對話裡回報：標題、時長、字幕來源、文章字數、檔案位置。
- **知識分類**：桌面啟動器會把輸出放在 `桌面\YT影片文章\<分類>\<標題>__<id>\`；指令通常已含「知識分類：X」。`build_index.py` 會掃所有分類夾，更新可搜尋的知識庫首頁 `桌面\YT影片文章\index.html`。

---

## 文檔進料（PDF／網頁文章／Markdown／Word）

非影音來源走 `fetch_document.py`（出口與 `fetch_transcript.py` 同 schema、`meta.type="document"`，第 2、3 步完全共用；因無時間軸，寫文時**不要求標時間碼**）：

```
python "<技能資料夾>\scripts\fetch_document.py" "<檔路徑或文章URL>" --base "桌面\YT影片文章"
```

- 吃本機 **PDF／md／txt／docx** 或**網頁文章 URL**，可混合多個輸入。（網頁抽正文：有裝 `trafilatura` 就用它、品質較好；沒裝走內建 stdlib 退路，仍可用。）
- **多來源綜合（`--merge`）**：把多份輸入合併成單一文章 → 全部進單一夾，`transcript.txt` 以 `【來源①：<名稱>】` 分節標明各段出處（`--title "合併標題"` 指定合併後標題；不給時為「首檔標題 等N份」）。寫文時保留這些 `【來源①…】` 標記，讓合成文章可回溯各段來源。
- `--private`：敏感內容標記——**不進知識庫 index、不嵌內文、不送 Obsidian vault**（三出口 fail-closed）。私密內容建議 `--out` 到庫外專夾，例如：
  `python … fetch_document.py "機密報告.pdf" --private --out "<你的庫外私密夾>\機密報告__doc-xxxxxxxx"`
  （不限文檔來源：任何來源的 `transcript.json` 只要在 `meta` 手動加 `"private": true`，`build_index.py` 都會整篇跳過、不入總覽也不嵌內文——影音來源同樣適用。）
- 其他：`--category 分類`／`--title 標題`／`--date YYYYMMDD`／`--selftest`（自驗）。
- PDF metadata 若是垃圾標題（`無題 1`／`Untitled`／`*.odt`…）會自動退回檔名；失敗寫夾內 `fetch_error.json`。

---

## 撰寫鐵則（嚴謹＝命脈；這段最重要）

### ① 忠實，不杜撰
- **只寫影片真的講過的東西**。不補影片沒提到的外部知識、不臆測、不腦補例子。
- 區分「講者主張／論點」與「客觀事實」；講者的意見就寫成「他主張／他認為」。
- 字幕含 `[Music]`/`[Applause]`/聽不清處：照實標注，不替它編台詞。
- 自動字幕（source=auto）或**語音辨識（source=whisper）**可能有同音錯字／斷句錯／專有名詞拼錯：用上下文合理修正明顯口誤，但**不得改變原意**；沒把握處保留原樣並可加（字幕似有誤）。**source=whisper 時，務必在回報中告知使用者「本片無字幕，內容由語音辨識產生，可能有誤」。**
- 數字、人名、書名、機構、年份、引述：**照字幕原樣**保留，必要時原文加註於括號（如：「敘事弧」(narrative arc)）。

### ② 完整，保留細節（這是對抗「摘要太短」的鐵律）
- 目標：**沒看過影片的人讀完文章，能掌握約 95% 的實質內容**。
- 影片**每一個論點、每一個例子、每一組數據、每一個步驟、每一段推理、每一個轉折**都要落進文章——不可把多個要點壓成一句空話。
- 一個段落講一件事；該展開的就展開。**篇幅隨影片內容長度走**（資訊密的長片，文章就該長）。
- 「精讀」≠ 逐字貼字幕：要去掉口水詞、重複、語助詞，把口語**重組成通順書面段落**，但資訊點一個都不能少。

### ③ 結構（文章形式，好讀）＋「帶得走」層（這是對抗「看不到能轉換應用」的鐵律）
渲染器（render_html.py）會**依固定標題字串**把對應段落自動變成卡片／清單／金句，所以**標題務必照下方逐字寫**（emoji 可保留）。骨架（用 Markdown）：

```
# 影片標題                       ← 第一個 # 會被當整篇標題放進 hero，不要重複

## 💡 重點洞察                    ← 必備：3–6 條「一句話」洞察 → 自動渲染成卡片格
- 一句話講清一個最關鍵的收穫（可帶 [時間碼]）
- …（3–6 條，等於全片的精華掃描，取代舊版 TL;DR）

## ⚡ 可應用 / 帶得走的行動         ← 必備·核心：3–8 條「明天就能做」的具體行動 → 自動渲染成可勾選清單
- 用祈使句、寫到「拿了就能照做」的程度，附 [時間碼]
- …（見下方「行動撰寫鐵律」）

---

## 章節標題 [0:16]                ← 正文：依影片章節切；無章節時自行每 5–10 分鐘一節
（內文段落；每節開頭標 [mm:ss]；重要原話用 > 引言；流程/比較用條列或 | 表格 |；可用下方 callout 強調）

## ❝ 金句                        ← 選用：把全片最有力的 3–5 句原話收進來 → 自動渲染成可複製金句卡
> 「原話一」 [12:34]
> 「原話二」 [45:06]

## 🧠 自我檢核                    ← 選用：3–6 題自我測驗 → 自動渲染成「點一下翻看答案」的複習卡＋可一鍵匯出 Anki
- 問題一？｜這裡寫答案（每行一題，用全形「｜」分隔問題與答案）
- 問題二？｜答案

## 關鍵結論 / 名詞解釋 / 延伸·待查   ← 結尾視內容加
```

**行動撰寫鐵律（「可應用 / 帶得走的行動」一節）**：
- 每條都要**具體、可執行、能驗收**——讀者照著就能做。
- ❌ 空泛：「要多練習」「注意投影片設計」。
- ✅ 具體：「把簡報印出來攤在桌上，每張砍到只剩幾個關鍵詞、字級≥40」「練習找『不懂你題目的朋友』聽，講到他聽懂為止」。
- 能附 `[時間碼]` 就附，方便回片確認出處。

**強調語法（callout，正文中可用）**——首行以標記開頭的 `>` 引言會變成彩色強調框：
```
> [!key]   重點框（海軍藍）——最該記住的一句
> [!note]  提示框（金）——補充說明
> [!warn]  注意框（紅）——警告/常見錯誤/別這樣做
> [!quote] 金句卡（單句，可複製＋跳片）
```
無標記的 `>` 仍是一般引言區塊（完全相容）。

> [!note] 逐字稿不用你寫——渲染器會自動從 transcript.json 注入可摺疊、可跳片的完整逐字稿。你的任務是把它「精讀成文章」。

### ④ 語言與翻譯
- 一律輸出**繁體中文**。原片非中文時，由你忠實翻譯；專有名詞、人名、關鍵術語、書名首次出現時於括號附原文。
- 譯文要自然、像給台灣讀者看的文章；但不可為了通順而省略或竄改資訊。

### ⑤ 不截斷
- 沿用「full-output」紀律：**絕不**輸出佔位、「同上」、「其餘類似」、「（內容省略）」。長就分段寫完。
- 寫完後自我檢查：每個章節都寫到了嗎？有沒有哪段字幕的內容沒對應到文章？補齊再渲染。

---

## 深度模式（預設：逐節精讀）
- **逐節精讀（預設）**：上述鐵則，最完整。使用者沒特別說就用這個。
- **快覽**：使用者明說「簡短一點／只要重點」時，只產「💡 重點洞察＋⚡ 可帶走的行動」＋各章兩三句。仍要忠實、不杜撰。
- **逐字精修**：使用者要「接近逐字」時，輸出清理後的完整對話（去口水詞、補標點、分段），保留近全部原話。

## 邊界與品質自檢（交付前）
- [ ] 有 `## 💡 重點洞察`（3–6 卡）與 `## ⚡ 可應用 / 帶得走的行動`（具體可執行清單）兩節，標題字串正確、被渲染成卡片/清單。
- [ ] `source` 是 auto/auto-translated 時，已在回報中告知使用者「字幕為自動產生，可能有誤」。
- [ ] 文章涵蓋所有章節；無遺漏整段未處理的字幕。
- [ ] 沒有杜撰影片未提及的內容；不確定處有適當標注。
- [ ] 時間碼能對到原片；`article.html` 已成功渲染並可打開。
- [ ] 三個檔都在同一個 `桌面\YT影片文章\<標題>__<id>\` 夾內。

## 工具檔案
- `scripts/fetch_transcript.py` —— 影音抓取＋字幕挑選＋解析（json3 主、vtt 備援；原語優先）；含 Podcast 連結正規化與財經科技詞庫校正。輸出 `meta.type="av"`。
- `scripts/fetch_document.py` —— 文檔進料口（PDF／網頁文章／md／txt／docx → 同 schema、`meta.type="document"`；支援 `--merge`／`--private`；`--selftest` 自驗）。零新依賴（PyMuPDF／標準庫）。
- `scripts/common.py` —— 共用常數單一定義（來源標籤 SRC_MAP／時間碼 regex／平台判定／安全檔名），供各腳本與啟動器共用。
- `scripts/render_html.py` —— 自帶極簡 Markdown→HTML；navy/gold 大字宋體閱讀版，時間碼可點回原片，含列印樣式。
- `scripts/build_index.py` —— 知識總覽首頁（全文搜尋＋分類標籤篩選）。
- `scripts/build_review.py` —— 每日回顧（間隔重複）：掃全庫 🧠 自我檢核卡，產獨立 navy/gold `review.html`（半衰期 7／14／28 天、二元回饋、狀態存 localStorage）。GUI 有「🧠 每日回顧」鈕，index 首頁有入口鈕。
- `scripts/export_formats.py` —— 匯出 `transcript.srt`／`.vtt`／`article.obsidian.md`（Obsidian 優化：原生 callout、YT 時間碼可點、block-list frontmatter）；**送進 Obsidian vault**：`python scripts/export_formats.py "<輸出夾>" --vault auto`（自動偵測 vault→寫進 `影片文章/`、依來源去重、首次建 `影片文章.base` 視圖）。GUI 有「↧ 匯出檔」與「📥 送到 Obsidian」鈕。
