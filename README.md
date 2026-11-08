# aicam-edgeops-agent（POC）

這是一款地端 AI Agent，專為自動排除 AI 攝影機系統（如：得來速計時等）故障所設計。

## 核心機制

- **階層式修復：** ***Agent 自動修復 → Operator 現場協助 → 遠端工程師（附 incident bundle）***。
- **觀測與追溯：** 支援查詢 logs、metrics、traces、歷史 issue 及歷史對話。
- **版本控制：** 所有設定變更皆會自動快照，支援查詢與 rollback（回滾）。
- **高度模組化：** 工具、RAG、Skill、MCP 介面、prompt、安全檢查皆可透過設定檔自由插拔。

## POC 專用限制

- `sim/`（邊緣端模擬與故障注入）與 Mock LLM（決定性規則＋模板）僅供 POC 使用，不屬於正式執行路徑。
- **網路模式：**
  - 離線時：自動使用 Mock LLM。
  - 連線時：可接 `Claude`、`OpenAI` 或 `OpenRouter`。
- **開發限制：** 目前開發環境無法驗證 Docker 與真雲端 LLM，詳見 `todo.md`。

## 快速開始（Host 只需 Docker Desktop 與瀏覽器）

```bash
make up        # 首次需網路 build；自動建立 .env（預設 LLM_PROVIDER=mock，離線可跑）
open http://localhost:8000
make test      # 在 Docker 內跑 pytest（不需要 Host Python）
make down      # 關閉服務
```

### 🛠️ 本機調校（加速 demo、關閉工具、功能開關…）

請將自訂設定寫在 config/agent.local.toml：

- **💡 使用方式：** `cp config/agent.toml config/agent.local.toml`（此檔案已被 git 忽略；若不存在則預設僅載入 agent.toml）。詳情請見 `docs/config-reference.md`。

### 🌐 切換真實模型（有網路環境）

1. `cp .env.example .env`
2. 編輯 `.env` 檔案
3. 設定 `LLM_PROVIDER=auto` 並填入對應的 API key
4. 執行 `make up`

#### 📊 UI 狀態顯示說明

- UI 標頭會如實顯示`REAL · provider/model` 或 `MOCK`。
- 當雲端連線失敗退回時，會顯示 `MOCK（… 失敗，已退回）`，***將游標移上去即可查看原因***。

#### 🔄 熱重載機制

改了 `.env` 或雲端曾失敗退回 Mock 時，只需按下 UI 的 ***「Reset」***（或 🛡️安全 →「重新載入 LLM」）即可依 .env 重建，不必重新執行 `make down`／`make up`。

### 📦 離線攜帶

在有網路環境封裝後，即可帶至離線機部署：
```bash
make pack                       # 在有網環境打包
make load && make up-offline    # 在離線環境載入並啟動
```

## 情境
| | 情境 | 展示 |
|---|---|---|
| A | 推論卡死 | Agent 自動：偵測 → 查證 → `restart_pipeline`(L1) → Verify → 報告 |
| B→C | 攝影機無訊號 | 重連失敗（預設 2 次，由 `max_attempts` 調整）→ Operator → 無法處理／逾時 → 遠端工程師 bundle |
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
