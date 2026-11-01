# ADR-003：POC 安全模型（Prompt 分層、Guard、功能開關）

- **Context**：Demo 要展示：接的是真大模型；可動態加入「只允許 Operator 做某些事」的提示詞；對使用者輸入與 AI 輸出做可插拔安全檢查。POC 的使用者固定為 Operator，不做 RBAC。
- **Options**：(a) 只靠 prompt 約束；(b) 完整 RBAC + guard；(c) prompt 分層 + 可插拔 guard + 設定檔功能開關。
- **Decision**：選 (c)。
  - Prompt 分層可編輯，但固定安全規則（untrusted 資料不是指令、LLM 只能提案、不得洩漏 prompt）不可編輯；含 canary 以偵測洩漏。
  - Guard pipeline 三階段（input／output／content）由 TOML 組裝，可用 python 模組擴充；規則式、可離線、決定性。
  - 越權功能（聊天、改 prompt、重載設定、工具啟停、LLM 連線測試、demo 控制）由 `[features]` 開關，關閉時 API 回 403。
  - 外部內容（log）先過 content guard 並包 `<untrusted>`；命中即標記，Agent 不得據以行動。
- **Consequences**：
  - 防線分層：prompt 只影響真 LLM；guard／Policy／功能開關由程式碼強制，Mock 與真 LLM 行為一致。Mock 不解讀 prompt，UI 與連線測試如實標示 `MOCK`。
  - 規則式 guard 可被刻意繞過，POC 明確接受；LLM 判官與 DLP 列為後續。
  - 無身分驗證：能連到服務者等同 Operator；正式版需 SSO／JWT 與 RBAC（本 ADR 的 `[features]` 可保留為功能旗標）。
