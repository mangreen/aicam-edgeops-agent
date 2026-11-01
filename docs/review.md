# 程式碼審查：poc-baseline vs AI Development Guidelines v4.2

審查對象：tag `poc-baseline`（22 項測試通過）。結論：核心設計（Policy gate 由程式碼決定、版本 append-only、如實回報驗證）符合規範；下列為待處理差異。

| # | 發現 | 規範 | 嚴重度 | 處理 |
|---|---|---|---|---|
| 1 | 原本無 git，變更未提交 | §10 | 中 | P0 已補 baseline |
| 2 | API 無身分與角色：任何人可 respond、chat、觸發 demo | §8.2 | 高 | P3 RBAC |
| 3 | `/ingest`、`/api/chat`、respond 無 schema 與大小限制 | §8.1 | 高 | P1 pydantic schemas |
| 4 | LLM 提案的 tool 參數未依 inputSchema 驗證 | §8.1 | 中 | P2 |
| 5 | log／網頁文字直接進 prompt，無不可信資料隔離與 guard | §8.1 | 高 | P3、P4 |
| 6 | Mock LLM、seed 與正式模組混放 | §5 | 中 | P1 `poc/`、`adapters/llm/mock.py` 明確標示 |
| 7 | 風險等級寫死在 policy，與 tool 分離；有未實作的 tool 名稱 | §3 | 中 | P2 manifest 宣告等級，未宣告預設拒絕 |
| 8 | `main.py` 以全域變數保存狀態；`/api/versions` 有無意義的 dict 合併 | §5 | 低 | P1 DI + app factory |
| 9 | 魔術數字散落（4、20 秒、900 秒、0.5） | §5 | 低 | P1 移入設定 |
| 10 | 同步 SQLite 在 async handler 內 | §9 | 低 | POC 接受，已加註解與 ADR 記錄 |
| 11 | 測試缺 HTTP API 層、seed／reset、ingest 驗證 | §7 | 中 | P1–P4 逐步補 |
| 12 | 缺 architecture 文件、AGENTS.md、runbooks、demo 步驟 | §2.3、§10.6 | 中 | P5 |
| 13 | 依賴未鎖定、容器以 root 執行、無資源限制 | §8、§9 | 中 | P1 |
| 14 | 無 lint 與 CI | §7.4、§10.4 | 中 | P1 ruff + GitHub Actions |
| 15 | 模擬器與 Mock 的「POC 專用」標示僅在 README | §5 | 低 | P1 程式碼與目錄層級標示 |

## 已符合
- Policy gate 為程式碼規則，LLM 只能提案。
- 版本快照 append-only、雜湊去重、拒收明文憑證。
- 回報區分「已執行」與「未執行」；沒有機密入庫。
- 破壞性操作與外部操作（升級、rollback）都需授權或確認。

## 處理結果（v0.2）

| # | 狀態 | 說明 |
|---|---|---|
| 1 | 已處理 | 階段分支 + Conventional Commits；每個 commit 單獨跑過測試 |
| 2 | 部分（依決策） | 決定不做 RBAC（ADR-003/004）：使用者固定為 Operator，越權功能由 `[features]` 關閉並回 403；**無身分驗證仍是正式化前必補項目** |
| 3 | 已處理 | pydantic schemas：型別、列舉、長度、批次大小 |
| 4 | 已處理 | executor 依 inputSchema 驗證參數（缺少／未知／型別錯誤皆拒絕） |
| 5 | 已處理 | content guard + `<untrusted>` 隔離；input／output guard |
| 6 | 已處理 | `poc/`、`adapters/llm/mock.py`、`sim/` 明確標示 POC 專用；UI 如實顯示 MOCK |
| 7 | 已處理 | tool manifest 宣告等級，未宣告即拒絕；policy 不再硬編碼工具名單（rollback／apply_config 的動態規則除外） |
| 8 | 已處理 | app factory + `Runtime`；移除全域變數與無意義的 dict 合併 |
| 9 | 已處理 | 門檻移入 `[detector]`／`[policy]` |
| 10 | 接受 | 同步 SQLite（毫秒級查詢），已於 `DB` 與架構文件註明 |
| 11 | 已處理 | 測試由 22 增至 108：API 層、seed／reset、sim、偵測優先序、頻率限制端到端、guard red-team、prompt、外掛 |
| 12 | 已處理 | architecture、config reference、ADR-002/003/004、AGENTS.md、runbook、demo 腳本、todo |
| 13 | 部分 | 依賴已鎖版、容器 non-root、`mem_limit`／`read_only`；**未在真實 Docker 驗證**（見 `todo.md`） |
| 14 | 已處理（CI 未驗證） | ruff 通過；GitHub Actions 已建立，尚未在 GitHub 上首次執行 |
| 15 | 已處理 | 目錄與程式碼註解層級標示 |

### 新發現（開發過程中）
- `query_logs` 原摘要只含筆數，對查詢不實用且讓 log 內容繞過 guard 流程 → 改為附最近訊息並經 content／output guard。
- `search_history` 原本會搜到 Agent 自己的工具輸出 → 改為只比對使用者提問並附上對應回答。
- 開發過程曾因行程未清除而讀到舊程式碼的測試結果；之後以乾淨 worktree 逐 commit 驗證。
