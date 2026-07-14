---
name: autoclip
description: 自動剪短影音爆款片段並燒錄字幕/狀聲詞。流程:faster-whisper 轉錄 → 抽 keyframe 拼圖 → Claude 同時看畫面+逐字稿選爆點(單一或多片段) → ffmpeg 剪切+燒字幕。Use when the user provides a video and wants highlight clips, shorts, viral segments, or auto subtitles.
---

# autoclip — 自動剪短影音

<!-- 安裝:把此資料夾複製到 ~/.claude/skills/autoclip/,並把下方 <PROJECT_DIR> 全部換成你 clone 專案的絕對路徑(例如 D:\videos\shorts) -->

專案位置:`<PROJECT_DIR>`(uv 專案,所有指令在此目錄下執行)。
每支影片建立工作目錄:`<PROJECT_DIR>\jobs\<影片名>\`。

## 流程

### 1. 轉錄(word-level 時間碼)

```
cd "<PROJECT_DIR>" && uv run scripts/transcribe.py "<影片路徑>" "jobs/<名>/transcript.json"
```

- 預設 `--model medium`(CPU int8)。影片很長或想先快速試跑用 `--model small`。
- 預設中文(`--lang zh`,prompt 引導繁體);其他語言用 `--lang auto`。
- 第一次執行會下載模型(medium 約 1.5GB),屬正常現象。
- CPU 轉錄約為影片時長的 0.3~0.5 倍,先告知使用者需要等待;超過 1 小時的影片先問是否改用 small。

### 2. 抽畫格拼圖

```
cd "<PROJECT_DIR>" && uv run scripts/frames.py "<影片路徑>" "jobs/<名>/sheets"
```

產出 `sheet_001.jpg ...`,每格左上角有 mm:ss 時間戳,預設每 4 秒一格、4x4 一張。
長影片(>30 分鐘)把 `--interval` 調到 8~10 避免 sheet 太多;短影片(<1 分鐘)可調 2。

### 3. 選爆點(核心判斷,由 Claude 執行)

用 Read 依序看完**所有** sheet 圖 + `transcript.json`,兩者交叉比對後選出片段。

判斷標準(重要性排序):
1. **前 3 秒 hook**:片段開頭必須有懸念、衝突、反常識金句或強烈畫面,能讓人停下滑動。
2. **可獨立理解**:不需要前後文就看得懂。開頭若是「所以」「然後」這種接續語,把起點往前移到完整句子。
3. **完整敘事弧**:有起頭、展開、收尾(punchline / 結論),不要斷在半句。
4. **情緒與畫面能量**:表情變化、動作、笑點、衝突處優先——這是看畫面的目的,逐字稿平淡但畫面有戲的段落不要漏掉。
5. **長度**:單片段以 20~60 秒為佳;多片段組合(如「三個重點」散在各處)總長 ≤ 90 秒。

輸出 `jobs/<名>/clips.json`(格式詳見 scripts/render.py 開頭註解):

```json
[
 {"slug": "hook-money", "title": "標題", "reason": "為什麼會爆", "parts": [[12.5, 42.0]],
  "sfx": [{"start": 13.0, "end": 15.0, "text": "哇！", "x": 0.5, "y": 0.28,
           "angle": -6, "scale": 1.2, "color": "#FFE066"}]}
]
```

- `start`/`end` 對齊 transcript 裡字詞的實際邊界(句首字前留 ~0.2s,句尾字後留 ~0.3s),不要切在字中間。
- `sfx` 是狀聲詞/字卡:看畫面在哭聲/笑聲/撞擊/誇張表情處加生動的狀聲詞,位置避開人臉;使用者給主題時做開頭主題字卡(`\N` 可換行)。
- 除非使用者指定數量,預設選 2~4 個候選,依爆款潛力排序,並向使用者說明每段的入選理由。

同時建立 `jobs/<名>/job.json`(編輯器與渲染的設定):

```json
{"video": "<影片絕對路徑>", "vertical": true,
 "style": {"dialog_font": "GenSenRounded2 TW B", "sfx_font": "GenSenRounded2 TW H",
  "dialog_font_file": "GenSenRounded2TW-B.otf", "sfx_font_file": "GenSenRounded2TW-H.otf",
  "outline": 0, "shadow": 4, "fontsize": 88, "sfx_size": 130}}
```

樣式依使用者需求調整(外框 vs 陰影、字體、字級);fonts/ 內的字體可用 PIL 查 family name。

### 4. 剪切 + 燒字幕

```
cd "<PROJECT_DIR>" && uv run scripts/render.py "<影片路徑>" "jobs/<名>/transcript.json" "jobs/<名>/clips.json" "jobs/<名>/out" --vertical
```

- `--vertical`:置中裁 9:16 輸出 1080x1920(短影音預設)。拿掉則保留原始橫幅。
- 多片段 clip 會逐段渲染後自動 concat,字幕與 SFX 自動對位。

### 5. 驗收與回報

- 對每個輸出檔用 ffprobe 確認時長符合預期。
- 抽 1~2 張輸出影片的畫格(ffmpeg `-ss ... -frames:v 1`)用 Read 檢查字幕有正常燒上、沒有亂碼或超出畫面。
- 回報:每個片段的檔案路徑、時長、標題、入選理由。

### 隱私檢查(必做)

轉錄完成後掃描逐字稿是否有**人名**(尤其小孩的名字)。有的話把該段語音從 parts 中切除(在字詞邊界前後留 0.2~0.5s 餘裕),並在回報時說明剪除位置。

## 編輯器

使用者想微調時:`cd "<PROJECT_DIR>" && uv run scripts/editor.py` → http://localhost:8765。
時間軸拖拉片段、畫面上直接拖字幕、Ctrl+Z 復原、「儲存並渲染」出片。

## 注意事項

- ffmpeg 由 `scripts/ffutil.py` 定位(含 winget 安裝路徑),不要假設在 PATH 裡。
- 使用者對爆點的回饋(太長、hook 不夠強、想要什麼類型、字體配色偏好)值得記進 memory,下次直接套用。
