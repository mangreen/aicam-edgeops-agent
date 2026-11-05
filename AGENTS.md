# AGENTS.md — aicam-edgeops-agent

AI Agent／開發者進入專案的穩定規則與入口。通用規範：AI Development Guidelines v4.2。

## 這是什麼
POC：地端 Agent 自動排除 AI 攝影機系統故障（Agent → Operator → 遠端工程師三層升級），可查詢 logs／metrics／traces／歷史 issue／歷史對話，具設定版本快照與 rollback。**MVP/POC：以精簡、可離線 demo 為先。**

## 入口
- 架構：`docs/architecture.md`；設定：`docs/config-reference.md`；決策：`docs/ADR-*.md`；demo：`docs/demo-script.md`；操作：`docs/runbooks/operations.md`；待辦：`todo.md`；審查：`docs/review.md`
- 程式：`agent/src/aicam/`（core／ports／adapters／plugins／prompts／api／poc）、`sim/app.py`（POC 模擬器）、`config/`、`tests/`

## 指令（Host 只需 Docker；不要用 Host 的 pip/python）
`make up | up-offline | down | reset | logs | test | test-ui | lint | pack | load | fault-A | fault-B | fault-E`

## 規則
1. 依賴方向：`api → core → ports ← adapters`；`core` 不得 import `adapters`。新外部依賴先定義 Port。
2. 所有工具呼叫只能走 `core/executor.execute`；新工具必須在 manifest 宣告風險等級（沒宣告即拒絕）。風險決策只在 `core/policy.py`（程式碼），不交給 LLM。
3. 外部內容（log 等）進 LLM 前須經 content guard 並包 `<untrusted>`。需要「證據」才能放行的動作（如 rollback），證據必須由程式碼計算（`Call.evidence`），不可接受 LLM 自填的參數。
4. 機密只放環境變數／`.env`（已 gitignore）；不得寫進 TOML、log、測試資料、回覆。
5. 標示「POC 專用」的元件（`sim/`、`poc/`、`adapters/llm/mock.py`）不得混入正式路徑。
6. 超出 Operator 權限的功能一律用 `[features]` 開關；不要新增未受控的管理端點。
7. 變更時：先跑 `make test`／`make lint`；行為變更要有測試；更新對應文件（架構、設定、demo 腳本）。
8. **未經使用者授權不得 push／merge 到遠端／發布**；commit 依授權進行，使用 Conventional Commits，分支依階段短生命週期。

## 驗證狀態慣例
區分 Implemented／Tested／Reviewed／Merged／Deployed；沒執行過的檢查不得標示為通過（目前未在真實 Docker 與真雲端 LLM 上驗證，見 `todo.md`）。
