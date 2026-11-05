# todo.md

## 需在有 Docker／金鑰的環境完成的驗證（開發環境無法執行）
- [x] `make test`、`make lint`、`make test-ui`：使用者在 Docker Desktop 實跑通過（之後有新增測試，請重跑）；`make up` 與以 OpenRouter 對話已由使用者實際使用
- [ ] `make pack`/`load`/`up-offline`、`.env` 單檔 bind mount 在 macOS 的更新行為（編輯器換檔時可能看到舊內容，需 `docker compose restart agent`）、Compose v2.10.2 對 `read_only`／`tmpfs`／`mem_limit` 的長時間運行
- [ ] 斷網演練 + 錄製備援影片
- [ ] 雲端 LLM 實測（已用 OpenRouter 發現參數與格式問題並修正，見 review）：plan／report 的 JSON 格式、prompt 層對真 LLM 的效果、不同模型的容錯差異；視結果微調預設模型名稱
- [ ] GitHub Actions CI 首次執行
- [ ] UI 在真實瀏覽器的視覺檢查（開發環境僅做 JS 語法檢查與 API 測試）

## 外部審查（v0.2.3）中決定延後的項目（POC 只修 bug，其餘成案再說）
- [ ] **認證與安全預設**：出貨的 `agent.toml` 為 demo 設定（`[features]` 全開、無認證），compose 的 8000／8001 綁全介面。成案前：預設只開 chat、綁 `127.0.0.1`、加 token／SSO；`/ingest` 加 HMAC；`respond` 驗證呼叫者角色與升級單的 `to_who`（目前任何人可代替工程師回 `fixed`）
- [ ] **Mock 退回與 core 的耦合**：`core/loop.py` 仍直接引用 `llm.mock`、`CloudLLM` 繼承 `MockLLM`、指定 provider 仍包成 `AutoLLM`。成案時加 `[llm] fallback_to_mock` 並把退回處理收進 adapter；LLM 失敗且不退回時直接升級 Operator（目前預設維持「自動退回 Mock」以保證 demo 順暢）
- [ ] **可替換性重構**：`IssueStore` Protocol 只宣告 3 個方法（實際用約 17 個，且混了 issue／event／action／escalation／message）；`EdgeControlPort` 混入 POC 專用的 `physical_fix`／`fault`／`reset`，且正式流程 `_operator`／`_engineer` 會呼叫 `physical_fix`（真實邊緣端沒有）；`seed.run` 在啟動時無條件執行、demo 路由混在正式 router；`routes.py`／`PromptStore` 直接寫 SQL；`policy.py` 寫死 `rollback_version`／`apply_config`
- [ ] **原生 tool calling**：可刪除 `cloud.py` 的 JSON 解析／重問／few-shot 與 `registry` 的別名轉換約 200 行；但免費模型（目前預設的 OpenRouter free 模型）常不支援原生 tools，需先確定正式使用的模型再評估
- [ ] **logging**：全專案沒有 `logging`，錯誤只有一處 `print`
- [ ] **時鐘偏移**：Detect／Verify 以 Agent 主機時間比對 edge 傳來的 `ts`；POC 同機不受影響，真實部署需以接收時間為準或容許偏移
- [ ] 小項：4 個內建工具模組有未使用的 `import Call  # noqa`；`config.py` 的 `PolicyCfg(**{**…})` 難讀

## 正式立案候選（POC 刻意不做，見 ADR-004）
- [ ] 身分驗證與 RBAC（SSO／JWT）；目前以 `[features]` 開關替代
- [ ] MCP client adapter（介面 `McpSourcePort` 已有）
- [ ] LLM 判官 guard、DLP；規則式 guard 可被刻意繞過
- [ ] 自建模型評測（Qwen 7–8B + vLLM／Ollama + bge-m3）；累積 Agent 軌跡後評估 LoRA
- [ ] 向量 RAG；SQLite → Postgres；Loki／Prometheus／Tempo；PagerDuty／LINE
- [ ] 分區版本（目前整份設定 rollback 會連帶還原無關變更）
- [ ] 雲地混合：AWS 彙整跨店分析
- [ ] 無頭瀏覽器／網路搜尋排錯（需評估映像大小、外網與網頁注入風險後再議）
- [ ] 授權檔（LICENSE）：公開 repo 尚未選擇授權，待擁有者決定
