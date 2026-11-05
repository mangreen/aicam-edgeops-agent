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

## v0.2.1 實機回饋與修正（使用者以 OpenRouter 實測）
| 問題 | 根因 | 修正 |
|---|---|---|
| 對話一按 Enter 就送出，中文輸入法選字時誤送 | UI 綁了 Enter 事件 | 只有按「送出」才送出；處理中停用按鈕並顯示 spinner |
| 查「lane 1 過去 2 天 metrics」失敗：`lane_id`／`duration`、「缺少必要參數 lane」，答案是一段工具呼叫 JSON | `chat_plan` 的 prompt 只有工具**名稱**沒有參數 schema，模型只能猜；回答階段又把答案寫成工具呼叫 | prompt 帶完整 schema；executor 參數校正；解析容忍變體；答案為工具呼叫 JSON 時改用結果摘要；一次附錯誤的重新規劃 |
| 格式錯誤也被當成雲端故障，鎖 30 秒 | `AutoLLM` 不分錯誤類型 | 格式錯誤只影響單次；連線錯誤才鎖定 |
| 退回 Mock 後只能 `make down && make up` | 容器環境變數建立時固定；Reset 不重建 LLM | `.env` 唯讀掛載 + `Runtime.reset_llm`；Reset／「重新載入 LLM」依 `.env` 重建 |
| 看到 MOCK 卻不知道為什麼 | 沒有原因資訊 | 徽章顯示退回狀態，tooltip 為 `last_error`；`make_llm` 會說明為何使用 Mock |

## v0.2.2 實機回饋與修正
| 問題 | 修正 |
|---|---|
| Prompt 層只能新增、編輯，無法刪除（刪除鈕藏在表單底部，需先填名稱，且看不出是刪哪一層） | 每個 UI 層在列表上直接有「刪除」（確認後執行；覆蓋檔案層者提示會恢復檔案層）；檔案層不顯示刪除鈕；後端對不存在／檔案層的刪除回 404 |
| 按「編輯」後編輯區在畫面下方，看不到有沒有帶入 | 平滑捲動到編輯區並聚焦內容欄、短暫高亮；表單標題顯示「編輯：名稱」；新增「清空表單」 |
| UI 行為沒有自動化測試 | 新增 `tests/ui/prompt_layers.sim.js`（`make test-ui`），在假 DOM 中實際執行 UI 的 JS（非真瀏覽器） |

## v0.2.3 實機回饋與修正（雲端 LLM 常回傳錯誤格式）
| 問題 | 根因 | 修正 |
|---|---|---|
| 問「我們之前聊果什麼？」出現「回應格式不符（invalid json）」並退回 Mock | ① 擷取 JSON 用「第一個括號到最後一個括號」，模型只要在後面多寫 `[1]`／`[搜尋歷史]` 就整段失敗；② 模型常直接用散文回答，沒有給 JSON；③ 沒有任何重試；④ 退回 Mock 後，含錯字的句子被導到錯誤的工具 | 逐位置 raw_decode；JSON mode + temperature 0（不支援時自動降級）；few-shot 與「不需要工具回空陣列」；失敗時附原因自動重問一次；Mock 意圖規則容錯；`search_history` 無關鍵字／搜不到時列最近對話；事件訊息附原始回覆片段 |
| `make test` 出現 StarletteDeprecationWarning | Starlette 的 TestClient 優先使用 `httpx2`，僅有 `httpx` 時發出棄用警告 | 開發依賴加入 `httpx2==2.16.0`（只影響測試；執行期的 LLM 呼叫仍用 `httpx`） |

## v0.2.4 外部審查（針對 v0.2.3）的查核與處置
審查報告的主張已逐項以程式碼重現。**7 項核心問題全部屬實**，次要項大多屬實，僅「respond 不是原子操作」不成立（同時 5 次請求只有 1 次成功、4 次 409，讀狀態與更新之間沒有 `await`）。POC 階段**只修 bug**，其餘延後（見 `todo.md`）。

| 問題 | 重現結果 | 處置 |
|---|---|---|
| 重啟後殘留 open issue 讓該車道永遠不再偵測 | `tick()` 回傳 0 個 task；handler 內二次例外會讓 issue 卡住 | **已修**：啟動 `recover()`（等待中的升級單重新接上，處理到一半的 issue 標記「重啟中斷」並結案讓偵測器重新偵測；升級也失敗則結案為 failed）；完成的 task 自動移除 |
| rollback「相關性證據」由 LLM 自填，Policy 只檢查非空 | `evidence="x"` 即自動 rollback 他人的變更 | **已修**：證據由 loop 的 `find_suspect` 以程式碼計算並放進 `Call.evidence`，executor 驗證其對應目前 head 與目標版本；`evidence` 不再是工具參數 |
| `execute()` 不檢查 `plannable`／`chat` | agent 來源可執行 `propose_rollback`、chat 來源可執行 `restart_pipeline` | **已修**：依呼叫來源檢查旗標；loop 自己的 triage 用 `system` 來源；`Call.origin` 預設改為 `system` |
| `_commit_push` 忽略 edge 回應 | 推送失敗仍回 `ok=True` | **已修**：回報失敗（版本保留，標記未同步）並於背景重試；rollback 推送失敗會升級而非宣稱成功 |
| ingest：NaN／極端 ts／交易卡死 | NaN 存成 NULL 使偵測迴圈每 2 秒拋 `TypeError`；ts +30 年回 200；一筆壞批次後所有寫入都失敗 | **已修**：拒絕 NaN／inf 與範圍外 ts（`[ingest]`）、忽略 NULL 樣本、三張表同一交易並在錯誤時 ROLLBACK；422 回應不再回顯原始輸入（否則 NaN 會讓錯誤回應本身 500）；`/api/events` limit 上限 500 |
| 工具無 timeout | 掛住的工具會卡住 loop | **已修**：`[runtime] tool_timeout`（預設 30 秒） |
| `normalize_args` 從文字抽數字並用於 L1 | `restart_pipeline(lane="Lane 1 and 2")` 對 Lane 1 執行 | **已修**：L1 以上只接受純數字字串，唯讀工具維持寬鬆 |
| 限頻訊息寫死「10 分鐘」 | 窗口改設定後訊息錯誤 | **已修** |
| `_post_verify` 的 task 沒保留參考 | event loop 只持弱參考 | **已修** |
| 認證、預設設定、Mock 耦合、可替換性、原生 tool calling、logging、時鐘偏移 | 事實屬實 | **延後**（見 `todo.md`；POC 維持 demo 設定與「自動退回 Mock」） |
