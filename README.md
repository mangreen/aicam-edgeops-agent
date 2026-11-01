# aicam-edgeopt-agent（POC）

地端 AI Agent，自動排除 AI 攝影機系統（得來速計時等）的故障：
**Agent 自動修復 → Operator 現場協助 → 遠端工程師（附 incident bundle）**；可查詢 logs／metrics／traces／歷史 issue／歷史對話；
所有設定變更自動快照，可查詢、可 rollback。工具、RAG、Skill、MCP 介面、prompt、安全檢查皆可由設定檔插拔。

> **POC 專用**：`sim/`（邊緣端模擬與故障注入）與 Mock LLM（決定性規則＋模板）不屬於正式執行路徑。離線時使用 Mock；有網路可接 Claude／OpenAI／OpenRouter。
> 開發環境無法驗證 Docker 與真雲端 LLM，見 [`todo.md`](todo.md)。

## 快速開始（Host 只需 Docker Desktop 與瀏覽器）
```bash
make up        # 首次需網路 build；自動建立 .env（預設 LLM_PROVIDER=mock，離線可跑）
open http://localhost:8000
make test      # 在 Docker 內跑 pytest（不需要 Host Python）
```
有網路想用真模型：編輯 `.env` → `LLM_PROVIDER=auto` 並填一組 API key → `make up`。
UI 標頭會如實顯示 `REAL · provider/model` 或 `MOCK`。離線攜帶：`make pack` → 離線機 `make load && make up-offline`。

## 情境
| | 情境 | 展示 |
|---|---|---|
| A | 推論卡死 | Agent 自動：偵測 → 查證 → `restart_pipeline`(L1) → Verify → 報告 |
| B→C | 攝影機無訊號 | 重連失敗 2 次 → Operator → 無法處理／逾時 → 遠端工程師 bundle |
| D | 對話查詢 | logs／metrics／traces／歷史 issue／歷史對話／版本；rollback 需 Operator 確認 |
| E | 壞設定 | 偵測數驟降 → 關聯近期變更 → 附 diff 與證據自動 rollback → Verify |
| 安全 | prompt 分層、guard、功能開關 | 輸入／輸出／外部內容檢查，越權意圖被擋，設定檔關閉功能 |

Demo 逐步操作：[`docs/demo-script.md`](docs/demo-script.md)（5 分鐘版＋完整版）。

## 文件
| | |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 架構、Agent loop、Policy Gate、版本、安全模型 |
| [`docs/config-reference.md`](docs/config-reference.md) | `config/agent.toml` 與環境變數 |
| [`docs/ADR-001…004`](docs/) | 技術選型、Hexagonal＋外掛、安全模型、POC 範圍 |
| [`docs/runbooks/operations.md`](docs/runbooks/operations.md) | 啟停、離線攜帶、疑難排解、擴充 |
| [`docs/review.md`](docs/review.md) | 對照開發規範的程式碼審查 |
| [`AGENTS.md`](AGENTS.md)／[`todo.md`](todo.md) | 給 Agent／開發者的規則與待辦 |

## 專案結構
```
agent/src/aicam/  core（loop·policy·executor·versions·guards）  ports  adapters（sqlite·llm·edge·guards）
                  plugins（tool registry·loader·skills·builtin）  prompts  api  poc（seed）
agent/ui/         單頁 UI（vanilla JS + SSE，無 CDN，可離線）      agent/runbooks/  RAG 知識來源
sim/              POC 邊緣端模擬器                                  config/          agent.toml、prompts、skills
tests/            pytest（policy／版本／場景／API／guard／prompt／sim）   slides/   簡報
```

## 範圍外（見 ADR-004）
RBAC／SSO（改用 `[features]` 開關）、MCP client 實作（僅介面）、無頭瀏覽器與網路搜尋、向量 RAG、模型訓練、K8s、完整可觀測性堆疊。
