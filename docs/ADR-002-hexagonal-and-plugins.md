# ADR-002：Hexagonal 結構與設定檔驅動的外掛

- **Context**：需求要求 tool、RAG、Skill、MCP、Function Call 可插拔，並能依客戶／環境由設定檔啟用或關閉；同時 POC 要精簡、可離線 demo、日後可替換各模組。
- **Options**：(a) 維持扁平模組、用 if 判斷開關；(b) Hexagonal（ports/adapters）加 manifest 式 tool registry；(c) 完整外掛框架（entry points、動態安裝）。
- **Decision**：選 (b)。核心只依賴 `ports/`；每個 tool 以 `ToolSpec` manifest 自帶 schema 與風險等級；`[tools]` 逐一開關；python 與 MCP 來源預設停用；沒有合法等級者無法註冊。MCP 只做 `McpSourcePort` 介面，不寫 client。Skills 以 `SKILL.md` 載入，依賴的工具被停用時自動失效。
- **Consequences**：
  - 風險等級跟著 tool 走，新增工具不必改 policy；停用的工具對 LLM 不可見、對 executor 不可執行（雙重保證）。
  - 設定打錯（未知工具／guard／MCP adapter）啟動即失敗，不會默默放行或停用。
  - 熱重載先建好新狀態再切換，錯誤時維持舊狀態。
  - 代價：多一層 manifest 與 loader；POC 不支援動態安裝套件，也不驗證外掛程式碼本身的安全性（外掛等同可信程式碼）。
