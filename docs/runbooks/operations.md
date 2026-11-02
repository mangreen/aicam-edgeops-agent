# 操作 Runbook（開發／demo 環境）

Host 只需 Docker Desktop 與瀏覽器。（macOS 內建的 `pip`／`python` 是 2.7，**不要用它**；所有 Python 都在容器內執行。）

## 啟動與停止
| 目的 | 指令 |
|---|---|
| 建置並啟動（需網路，首次） | `make up`（會自動建立 `.env`），UI：http://localhost:8000 |
| 離線啟動（映像已存在） | `make up-offline` |
| 停止 | `make down`（資料保留在 volume `agent-data`） |
| 看 log | `make logs` |
| 重置 demo 狀態 | `make reset`（清空資料並重新 seed；UI 層 prompt 也會清除） |
| 完全清除 | `docker compose down -v` |

## 測試與檢查
- `make test`：在 Docker 內跑 pytest（首次需網路 build 測試映像，之後可離線）。
- `make lint`：ruff。
- `make test-ui`：以 Node 容器（`node:20-alpine`，需先 pull）在最小假 DOM 中執行 `agent/ui/index.html` 的 JS，驗證 Prompt 層的刪除與編輯捲動；非完整瀏覽器測試。
- CI（GitHub Actions）：ruff + pytest（Python 3.11）。

## 離線攜帶
1. 有網路：`make pack` → 產生 `aicam-images.tar`（已列入 `.gitignore`）。
2. 離線機器：`make load` → `make up-offline`。

## 修改設定
- 設定檔 `config/agent.toml` 以唯讀 bind mount 掛入容器，直接用編輯器修改，再於 UI ⚙能力 按「重載設定檔」。欄位說明見 `docs/config-reference.md`。
- 改 `.env`（LLM provider／金鑰）：`.env` 以唯讀掛入容器，按 UI **Reset**（或 🛡安全 →「重新載入 LLM」，或 `POST /api/llm/reset`）即依 `.env` 重建 LLM，**不必重啟容器**；`.env` 的值優先於容器建立時的環境變數。
  - 若編輯器以「換檔」方式存檔（部分 vim 設定）導致容器仍看到舊內容：`docker compose restart agent`。
  - 其他非 LLM 的環境變數（`DB_PATH`、`SIM_URL`…）仍需 `make up` 重新建立容器。
- 切換 LLM：`LLM_PROVIDER=mock`（離線）｜`auto`（有金鑰且可連線則用雲端，失敗自動退回 Mock）｜`anthropic`｜`openai`｜`openrouter`。

## 新增能力
- **新工具**：寫一個模組，用 `Toolbox` 宣告（必須指定 `level`），放進 `PYTHONPATH`，在 `[tool_sources] python` 登記並於 `[tools]` 明確啟用。參考 `agent/src/aicam/plugins/builtin/`。
- **新 guard**：模組提供 `GUARDS = {"名稱": class}`（`check(stage, text, ctx) -> GuardResult`），在 `[guards] python` 登記並加入對應 stage 的 `chain`。
- **新 skill**：`config/skills/<name>/SKILL.md`，並加到 `[skills] enabled`。
- **新 prompt 層**：`config/prompts/*.md`（或 UI 即時新增）。

## 疑難排解
| 症狀 | 原因與處置 |
|---|---|
| UI 載入但沒有資料 | sim 尚未就緒：`docker compose ps`、`make logs`；agent 會重試推送設定 |
| `重載設定檔` 回 400 | 設定有誤（未知工具／guard 名稱、未安裝的 MCP adapter、TOML 語法）；訊息已說明，原設定仍生效 |
| 對話／按鈕回 403 | 對應 `[features]` 為 false，這是設計行為 |
| 標頭顯示 MOCK | 滑鼠移到徽章看原因（沒金鑰／離線／雲端失敗）；改好 `.env` 後按 Reset 即恢復。連線類錯誤會鎖定雲端 30 秒，Reset 可立即解除 |
| 雲端模型常回「參數驗證失敗」 | 已內建參數校正（lane_id→lane、"2d"→48 小時）與一次附錯誤訊息的重新規劃；仍失敗時事件時間軸會有 `參數已校正`／`policy` 紀錄可查原因，必要時換更強的模型（`OPENROUTER_MODEL`） |
| 場景 A 後同一車道又立刻出現 issue | 檢查 `[detector]` 設定；正常情況下結案後只看新樣本 |
| `make test` 失敗找不到 Docker | 啟動 Docker Desktop；本專案不需要 Host Python |

## 資料與備份
SQLite 在 volume `agent-data`（`/data/agent.db`）。備份：`docker run --rm -v aicam-edgeopt-agent_agent-data:/d -v "$PWD":/b alpine cp /d/agent.db /b/agent.db.bak`（volume 名稱以 `docker volume ls` 為準）。Demo 資料可隨時 `make reset` 重建，不需備份。
