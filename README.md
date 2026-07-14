# autoclip — AI 自動剪短影音工具

丟一支影片進來，AI 自動找出爆點片段、剪輯、上字幕和狀聲詞，再用網頁編輯器微調後輸出。

```
影片 → ① 語音轉錄(逐字時間碼) → ② AI 看畫面+逐字稿選爆點 → ③ 剪切 → ④ 燒字幕/狀聲詞 → 成品
                                         ↕
                                   網頁編輯器微調(拖時間軸、改字幕、狀聲詞拖拉定位)
```

## 特色

- **AI 選段**:搭配 [Claude Code](https://claude.com/claude-code) 使用,AI 同時分析畫面(keyframe 拼圖)和逐字稿,找出有 hook、敘事完整的片段,支援多片段串接
- **逐字級字幕**:faster-whisper 轉錄含逐字時間碼,可做卡拉OK效果;純 CPU 可跑,不需要 GPU
- **狀聲詞/字卡系統**:任意文字、顏色、字體、角度、大小,彈出動畫,`\N` 換行
- **網頁編輯器**:時間軸拖拉剪輯、字幕直接在畫面上拖曳(中線自動吸附)、每條字幕獨立字體/顏色、Ctrl+Z 復原、一鍵渲染
- **隱私設計**:工作流程內建「掃描逐字稿中的人名並剪除」步驟

## 需求

- Windows(編輯器/腳本以 Windows 為主;macOS/Linux 需自行調整 ffmpeg/字體路徑)
- [uv](https://docs.astral.sh/uv/)(Python 套件管理)
- ffmpeg:`winget install --id Gyan.FFmpeg -e`
- (選用)Claude Code — 用於 AI 自動選段;不用的話編輯器可獨立手動剪

## 安裝

```bash
git clone <this-repo>
cd shorts
uv sync

# 下載字體(開源 SIL OFL 授權)
curl -sL -o gs.zip https://github.com/ButTaiwan/gensen-font/releases/download/v2.100/GenSenRounded2TW-otf.zip
unzip -o gs.zip -d fonts/ && rm gs.zip
curl -sL -o gl.zip https://github.com/welai/glow-sans/releases/download/v0.93/GlowSansTC-Normal-v0.93.zip
unzip -o gl.zip -d fonts/tmp && cp fonts/tmp/GlowSansTC-Normal-Bold.otf fonts/tmp/GlowSansTC-Normal-Heavy.otf fonts/ && rm -r fonts/tmp gl.zip
```

## 使用

### 方式一:AI 全自動(Claude Code)

1. 把 `skill/autoclip/` 複製到 `~/.claude/skills/autoclip/`,並把 SKILL.md 裡的 `<PROJECT_DIR>` 改成你 clone 的路徑
2. 開 Claude Code,丟影片說「幫我剪這支,主題是…」
3. AI 會轉錄 → 看畫面選爆點 → 產生初稿到 `jobs/<名>/out/`

### 方式二:手動 + 編輯器

```bash
# 1. 轉錄(第一次會下載 whisper 模型)
uv run scripts/transcribe.py "path/to/video.mp4" jobs/myclip/transcript.json

# 2. 建立任務設定 jobs/myclip/job.json:
#    {"video": "path/to/video.mp4", "vertical": true}
#    和 jobs/myclip/clips.json(片段與字幕,格式見 scripts/render.py 開頭註解)

# 3. 開編輯器調整
uv run scripts/editor.py     # → http://localhost:8765

# 4. 在編輯器按「儲存並渲染」,或手動:
uv run scripts/render.py "video.mp4" jobs/myclip/transcript.json jobs/myclip/clips.json jobs/myclip/out --vertical
```

### 編輯器操作

| 操作 | 方式 |
|---|---|
| 調整片段起訖 | 時間軸拖藍色區塊邊緣;拖中間整段移動 |
| 移動字幕位置 | 直接在影片畫面上拖曳,靠近中線自動吸附 |
| 字幕樣式 | 字幕分頁:顏色、字體、大小(x)、角度(°)、置中按鈕 |
| 復原/重做 | Ctrl+Z / Ctrl+Y |
| 成片預覽 | 勾選後播放會自動跳過剪掉的部分 |
| 輸出 | 輸出分頁 →「🎬 儲存並渲染」 |

## 樣式設定

`jobs/<名>/job.json` 的 `style` 可覆寫整體樣式:

```json
{
  "video": "path/to/video.mp4",
  "vertical": true,
  "style": {
    "dialog_font": "GenSenRounded2 TW B",
    "sfx_font": "GenSenRounded2 TW H",
    "dialog_font_file": "GenSenRounded2TW-B.otf",
    "sfx_font_file": "GenSenRounded2TW-H.otf",
    "outline": 0, "shadow": 4, "fontsize": 88, "sfx_size": 130
  }
}
```

`outline`(黑外框)/`shadow`(陰影)擇一或並用;想加新字體把 .otf/.ttf 丟進 `fonts/` 再重啟編輯器。

## 致謝

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 語音辨識
- [FFmpeg](https://ffmpeg.org/) — 影音處理
- [源泉圓體](https://github.com/ButTaiwan/gensen-font)、[未來熒黑 Glow Sans](https://github.com/welai/glow-sans) — 開源字體(SIL OFL)
