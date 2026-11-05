# 設定參考

主設定檔：`config/agent.toml`（容器內為 `/app/config/agent.toml`，compose 以唯讀 bind mount 掛入，可直接用編輯器修改）。
修改後：UI「⚙ 能力」→「重載設定檔」，或 `POST /api/admin/reload`（需 `features.admin_reload = true`）。
設定有誤時重載會失敗並維持原設定（回 400 與原因）。**機密只放環境變數／`.env`，不要寫在 TOML。**

## 環境變數（覆寫 TOML／提供機密）

| 變數 | 說明 | 預設 |
|---|---|---|
| `AICAM_CONFIG` | 設定檔路徑 | 容器 `/app/config/agent.toml` |
| `DB_PATH` / `SIM_URL` | SQLite 路徑／邊緣控制 API | `/data/agent.db`／`http://sim:8001` |
| `VERIFY_WAIT` / `OPERATOR_TIMEOUT` | 覆寫 `[runtime]` 同名鍵 | 7／30 秒 |
| `AICAM_ENV_FILE` | Reset 時讀取的 `.env` 路徑（compose 已將 `./.env` 唯讀掛到 `/app/.env`） | `/app/.env` |
| `LLM_PROVIDER` | `mock`｜`auto`｜`anthropic`｜`openai`｜`openrouter` | `mock`（`.env.example`） |
| `ANTHROPIC_API_KEY` `OPENAI_API_KEY` `OPENROUTER_API_KEY` | 雲端 LLM 金鑰（只放 `.env`） | 空 |
| `ANTHROPIC_MODEL` `OPENAI_MODEL` `OPENROUTER_MODEL` `OPENAI_BASE_URL` | 模型名稱／相容端點 | 見 `.env.example` |

**LLM 相關變數（`LLM_PROVIDER`、各 API key／model、`OPENAI_BASE_URL`）可在不重啟下生效：按 UI Reset 會重新讀取 `.env`，且 `.env` 的值優先於容器建立時的環境變數。**

`auto`：有金鑰且該服務可連線才使用雲端，否則 Mock；執行中雲端失敗會退回 Mock，30 秒內不再重試。

## `[runtime]`
`tool_timeout`（單一工具執行上限秒數，預設 30，逾時視為失敗）、`verify_wait`（動作後等待秒數）、`operator_timeout`（Operator 逾時，demo 為 30 秒）、`detect_samples`（連續幾筆異常才建 issue）、`lanes`。

## `[ingest]`
`max_future_sec`（預設 300）、`max_past_sec`（預設 30 天）：`POST /ingest` 的 `ts` 必須落在接收時間前後這個範圍內，否則整批回 422。另外 `NaN`／`inf` 與負的 `dur_ms` 一律拒絕。

## `[detector]`
`window_sec`（只看最近 N 秒樣本）、`min_detections`（低於視為驟降／Verify 需高於）、`suspect_window_sec`（變更與異常的關聯視窗）、`drop_ratio`（變更後平均 < 變更前 × ratio 才視為相關）、`healthy_min_samples`。

## `[policy]`
`l1_max_per_10min`（可被設定版本內的 `policy.l1_max_per_10min` 覆寫）、`rate_window_sec`、`agent_writable`（Agent 自行 `apply_config` 只能改的路徑，fnmatch，預設 `lanes.*.decoder_profile`、`lanes.*.fps_threshold`）。

## `[features]`：超出 Operator 權限的功能（取代 RBAC）
| 鍵 | 預設（程式） | 作用 | 關閉時 |
|---|---|---|---|
| `chat` | true | 對話查詢 | `POST /api/chat` 403、UI 隱藏對話 |
| `tool_toggle` | false | 能力面板可執行期啟停工具 | `PUT /api/admin/tools/*` 403 |
| `admin_reload` | false | 熱重載設定檔 | `POST /api/admin/reload` 403 |
| `prompt_edit` | false | 新增／修改／刪除 prompt 層 | prompt 寫入 API 403、UI 唯讀 |
| `llm_probe` | false | LLM 連線測試 | `POST /api/llm/probe` 403 |
| `demo_controls` | false | 故障注入與 Reset | `/api/demo/*` 403、UI 隱藏 |

`config/agent.toml` 的 demo 設定把以上全開；正式環境應只留 `chat`（必要時），並關閉 `demo_controls`。

## `[tools]`
`default_enabled`（內建工具預設，true）與每個工具一行：`restart_pipeline = false`。
未知工具名稱會讓載入失敗（避免打錯字而默默停用安全工具）。
內建工具：`get_status query_logs query_metrics query_traces`（L0）、`search_knowledge search_issues search_history`（L0）、`list_versions get_version diff_versions propose_rollback`（L0）、`restart_pipeline reconnect_stream apply_config rollback_version`（L1）。

## `[tool_sources]`
- `python = ["pkg.mod"]`：模組需提供 `TOOLS`（用 `Toolbox` 宣告，必須指定 `level`）。外部工具**預設停用**，須在 `[tools]` 明確 `name = true`。
- `mcp.<name>`：只有介面（`McpSourcePort`）。`adapter` 必須已註冊於 `plugins.loader.MCP_ADAPTERS`，否則啟動失敗。MCP 工具沒在 `levels` 宣告等級者一律 L3。

## `[knowledge]`
`sources = ["runbook", "issue"]`：`search_knowledge` 可檢索的 FTS5 kind。

## `[skills]`
`enabled = [...]`；`dir` 預設為設定檔旁的 `skills/`。Skill 格式：`skills/<name>/SKILL.md`，frontmatter 含 `name`、`description`、`tools`（逗號分隔）。需要的工具被停用時 skill 自動失效，不注入 prompt。

## `[prompts]` 與 prompt 檔
檔案層：`config/prompts/*.md`，frontmatter：`name`、`scope`（`agent｜chat｜all`）、`priority`（小者在前）、`enabled`（預設 true）。
UI 層存於資料庫，同名時覆蓋檔案層；刪除 UI 層即恢復檔案層。`Reset` 會清除 UI 層。
UI（🛡安全 → Prompt 層）：每個 UI 層都有「編輯」「刪除」（刪除前會確認）；檔案層只有「編輯」（儲存後建立同名 UI 覆蓋層，原檔不變），不能由 UI 刪除。按「編輯」會自動捲到編輯區並聚焦。
API：`DELETE /api/prompts/{name}` 找不到 UI 層（含只存在於檔案層）回 404；需 `features.prompt_edit = true`。

## `[guards]`
```toml
[guards]
python = []                      # 自訂 guard 模組：GUARDS = {"名稱": class}
[guards.input]   chain = ["length", "injection", "role_scope"]
[guards.output]  chain = ["secret_redact", "prompt_leak", "unsafe_command"]
[guards.content] chain = ["content_injection"]
[guards.conf.length] max_chars = 1000
[guards.conf.role_scope] deny = ["regex", ...]   # 覆寫 Operator 禁止意圖
[guards.conf.injection]  extra = ["regex", ...]  # 追加 injection 樣式
```
每個 guard 回傳 `allow｜block｜redact｜flag`；`block` 立即中止，`redact` 串接，`flag` 累積。命中會記錄為時間軸事件（type `guard`）。
未知 guard 名稱載入失敗。
