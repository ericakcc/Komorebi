---
name: LayerWise
status: active
priority: 1
started: 2026-01-14
repo: ~/LayerWise
---

# LayerWise

## 目標
將半色調網點印刷品轉換為平滑向量圖形的專業工具。針對物理製程（雷射雕刻、CNC 切割、網版印刷）優化，消除印刷網點、產生製程友好的 SVG 輸出。

## 技術棧
- Language: Python 3.12
- Package Manager: uv (Astral)
- Framework: FastAPI (REST API)
- Core: pypotrace (Bézier 向量描摹)
- Image: scipy (形態學運算), Pillow (圖片處理)
- AI: Google Gemini API (前處理、去背、銳化)
- PDF: fpdf2, weasyprint, cairosvg
- Testing: pytest, pytest-asyncio, httpx
- Dev: ruff (linting & formatting)

## 當前進度
### ✅ 已完成
- [x] 核心 PNG→SVG 轉換管線（7 步驟管線）
- [x] FastAPI REST API（前處理、轉換、狀態、下載）
- [x] Gemini API 前處理整合（extract_and_sharpen）
- [x] 非同步任務管理
- [x] 多圖層 SVG 合併（Illustrator 圖層識別）
- [x] 自動色彩偵測（基於亮度分析）
- [x] 可調參數系統
- [x] 完整測試覆蓋（pytest）
- [x] 專案重構與格式化（ruff）

### 🔄 最近更新
- c35de95 - add .env.example and fix .gitignore for pdf files
- 0176ef1 - simplify processor with extract_and_sharpen prompt
- d215403 - reorganize project structure and move scripts
- c72ad59 - apply ruff formatting across codebase
- 346e4eb - integrate Nano Banana Pro (Gemini 3 Pro Image API)

## Blockers
- (無)

## 進度日誌
### 2026-01-15
- 同步專案資訊（從 repo 讀取 README、CLAUDE.md、git log）
- 更新專案目標、技術棧、進度

### 2026-01-14
- 初始化專案追蹤
