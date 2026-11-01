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
