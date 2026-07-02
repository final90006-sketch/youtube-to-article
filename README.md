# 影片轉文章｜YouTube / Podcast → 繁中精讀長文（Claude Code 技能）

貼一個 YouTube 或 Podcast 連結，就把整支影片／整集節目變成一篇**讀完＝看完**的繁體中文精讀長文（不是三行摘要，而是保留所有細節、可點時間碼跳回原片的長文），並自動歸進本機可搜尋的知識庫。純本機、不需 API 金鑰、資料不出你的電腦。

---

## 這是什麼

- **立場是「精讀」不是「摘要」**——寧長毋短，影片講過的實質內容都留下。
- 產出：`article.md`（原稿）＋ `article.html`（navy/gold 精緻閱讀版，時間碼可點回原片該秒）＋ 逐字稿。
- 額外自動產：**一頁精華卡 `digest.html`**、**章節心智圖 `mindmap.html`**、**自測翻牌卡 `quiz.html`**（都是離線單檔）。
- 全部歸進 `桌面\YT影片文章\` 的可搜尋知識總覽首頁。

---

## 安裝（三步，一次性）

### 1) 把技能放進 Claude Code 的 skills 目錄

**方法一：git clone（推薦，日後 `git pull` 就能更新）**

```
# Windows
git clone https://github.com/final90006-sketch/youtube-to-article "%USERPROFILE%\.claude\skills\影片轉文章"

# Mac / Linux
git clone https://github.com/final90006-sketch/youtube-to-article ~/.claude/skills/影片轉文章
```

**方法二：直接下載 zip** → 解壓後把裡面的檔案放到 `你的使用者資料夾\.claude\skills\影片轉文章\`。

不論哪種方法，放好後結構應是 `…\.claude\skills\影片轉文章\SKILL.md`（SKILL.md 要在這一層）。

### 2) 裝依賴
需要 **Python 3.10+**，然後：

```
python -m pip install -U yt-dlp customtkinter faster-whisper
```

- `yt-dlp`：抓字幕／中繼資料（**必裝**）
- `customtkinter`：只有要用桌面 GUI 才需要
- `faster-whisper`：只有處理「沒有字幕的 Podcast／影片」時才需要（會用語音辨識；有 NVIDIA GPU 自動加速）

還需要 **ffmpeg**（處理音訊用）：
- Windows：`winget install Gyan.FFmpeg`（或 `choco install ffmpeg`）
- Mac：`brew install ffmpeg`

### 3) 重啟 Claude Code
重開後，這個技能才會出現在 `/` 選單、也才會自動觸發。

---

## 怎麼用

### 方式 A：對話版（推薦，品質最高）
在 **Claude Code 對話**裡貼上 YouTube／Podcast 連結，說「幫我做成文章 / 看不完 / 要重點」即可——技能會自動觸發，由**你這個 Claude session 直接撰寫**，不需要任何額外登入。

> 例：`https://www.youtube.com/watch?v=xxxx 幫我做成精讀文章`

### 方式 B：桌面 GUI（選用，可批次）
用來一次貼多個連結批次處理：

```
python "C:\Users\<你的帳號>\.claude\skills\影片轉文章\launcher.pyw"
```

⚠️ **GUI 的「撰寫」步驟是另外開一個 `claude -p` 子程序**，所以它需要你的 **Claude CLI 已登入**。若 GUI 顯示「claude 未登入 · 撰寫被擋下」，按右下「🔑 修復登入」，或在終端機跑一次：

```
claude auth login        （或 claude setup-token，長效）
```

登入一次之後就不會再擋。（對話版沒有這個問題——它用你當前的 session。）

---

## 支援的來源

YouTube、X(Twitter)、Vimeo，以及 Apple Podcasts（單集連結，含 `?i=`）、SoundCloud、Firstory、SoundOn、任何 Podcast RSS／`.mp3`。
**Spotify 不支援**（DRM 保護，抓不到）——請改貼同一集的 Apple Podcasts／RSS／YouTube 連結。

---

## 輸出位置

```
桌面\YT影片文章\
├─ index.html                    ← 知識總覽（可搜尋／篩選／排序）
└─ <知識分類>\<標題>__<id>\
   ├─ article.md / article.html  ← 精讀文章（原稿＋閱讀版）
   ├─ digest.html                ← 一頁精華卡（可列印）
   ├─ mindmap.html               ← 章節心智圖
   ├─ quiz.html                  ← 自測翻牌卡
   └─ transcript.json / .txt     ← 逐字稿
```

---

## 疑難排解

| 症狀 | 解法 |
|---|---|
| 技能沒出現／沒觸發 | 確認 `SKILL.md` 在 `…\.claude\skills\影片轉文章\` 這層，然後**重啟 Claude Code** |
| `找不到 yt-dlp` | `python -m pip install -U yt-dlp` |
| Podcast 抓不到、要語音辨識卻報缺套件 | `python -m pip install -U faster-whisper`，並確認裝了 ffmpeg |
| GUI 顯示「claude 未登入」 | 終端機跑 `claude auth login`（或按 GUI 的「🔑 修復登入」）；對話版無此問題 |
| 貼 Spotify 沒反應 | Spotify 有 DRM，改貼 Apple Podcasts／RSS／YouTube 連結 |

---

## 說明

- `finance_tech_lexicon.json` 是語音辨識的**同音錯字校正詞庫**（含財經／科技名詞），純粹讓 Podcast 逐字稿更準，可自行增刪或刪掉不用。
- `categories.json` 是知識分類清單，GUI 會自動維護；想改分類直接編它即可。
- 所有 `.html` 都是**零依賴離線單檔**，雙擊即開、可離線看、可自由散布。
- 本技能純本機運作、不需 API 金鑰、不上傳任何資料。
