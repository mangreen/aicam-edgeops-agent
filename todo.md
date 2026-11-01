# todo.md

## 需在有 Docker／金鑰的環境完成的驗證（開發環境無法執行）
- [ ] `make up`、`make test`、`make lint`、`make pack`/`load`/`up-offline`：Docker Desktop 4.12 / Compose v2.10.2 實跑（含 `read_only: true`、`tmpfs`、`mem_limit`、bind mount 唯讀 config）
- [ ] 斷網演練 + 錄製備援影片
- [ ] 雲端 LLM 實測（`LLM_PROVIDER=auto` 與金鑰）：plan／report／chat 的 JSON 格式、`REAL` 徽章、prompt 層對真 LLM 的效果；視結果微調 `anthropic`／`openrouter` 預設模型名稱
- [ ] GitHub Actions CI 首次執行
- [ ] UI 在真實瀏覽器的視覺檢查（開發環境僅做 JS 語法檢查與 API 測試）

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
