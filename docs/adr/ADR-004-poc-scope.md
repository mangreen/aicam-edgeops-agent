# ADR-004：POC 範圍取捨

- **Context**：MVP/POC 要在斷網下做 3~5 分鐘 live demo，且以核心情境與安全展示為重。
- **Decision**：明確**不做**以下項目，避免分散風險與增加 demo 不確定性：
  - 無頭瀏覽器與網路搜尋排錯（含相關情境）：需要大型映像與外網，離線 demo 不可靠；網頁內容也擴大攻擊面。核心情境改以 runbook／歷史 issue 的 RAG 處理。
  - RBAC／SSO：改用 `[features]` 開關（見 ADR-003）。
  - MCP client 實作：只保留介面。
  - 原生 function calling、向量 RAG、模型訓練、K8s、完整可觀測性堆疊、多租戶。
- **Consequences**：核心情境（A 自動修復、B→C 升級、D 對話查詢、E 版本 rollback）與安全展示可完整離線運行；上述項目列入 `todo.md` 作為正式立案時的候選。
