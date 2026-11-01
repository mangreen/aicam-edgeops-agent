# aicam-edgeopt-agent（POC）

AI 攝影機系統自主維運 Agent：偵測 → Triage → 規劃 → Policy Gate → 執行 → Verify → 報告／升級（Operator → 遠端工程師）；
支援 logs/metrics/traces、歷史 issue、歷史對話查詢，以及設定版本快照與 rollback。

> **POC 專用**：`sim/`（模擬邊緣端與故障注入）與 Mock LLM（決定性規則 + 模板）不屬於正式執行路徑。

## 啟動（只需 Docker + 瀏覽器）
```
cp .env.example .env     # （make up 會自動建立）預設 LLM_PROVIDER=mock（離線）；有網路可改 auto 並填 key
make up                  # build 並啟動，UI: http://localhost:8000
make test                # 在 Docker 內跑 22 項 pytest（Host 不需 Python）（policy / 版本 / 場景 A、B→C、E / 聊天）
```
Demo 控制：UI 右上按鈕，或 `make fault-A | fault-B | fault-E | reset`。
離線 demo 前請先在有網路時 `make up` 完成 build，再斷網演練一次。

## Demo 劇本（約 4 分 20 秒）
| 段落 | 操作 | 預期 |
|---|---|---|
| A 自動修復 | `fault-A` | ~15s：偵測→查詢→restart_pipeline(L1)→Verify→報告 |
| B→C 升級 | `fault-B` → Operator 面板按「無法處理」 | reconnect 失敗 2 次→請 Operator→遠端工程師收到 bundle→按「工程師已修復」 |
| D 對話 | 「Lane 1 過去 7 天斷線幾次？」「上次類似問題怎麼解？」「我們之前聊過 Lane 2 的什麼？」「回到上一版」→ Operator 面板確認 | 查 logs/issue/歷史對話；rollback 先顯示 diff 再確認 |
| E 版本 rollback | `fault-E` | ~13s：偵測數驟降→關聯 v7 變更→rollback 到 v6（L1，附 diff 與證據）→Verify |

> 順序提醒：「回到上一版」的對話示範請在 **E 之前**做（此時上一版 v5 無害）；E 之後的「上一版」是壞設定 v7。

## 架構（Port → POC adapter → 正式版）
LLMProvider: Mock/OpenAI-compat/Anthropic → vLLM/Ollama ｜ ObservabilityPort: SQLite → Loki/Prometheus/Tempo ｜ KnowledgePort: FTS5 → 向量庫 ｜ IssueStore/VersionStore: SQLite → Postgres/Git ｜ Notifier: outbox → PagerDuty/LINE ｜ Tools: 內部 registry（MCP 相容 schema，`GET /api/tools`）

風險等級由程式碼 policy 決定（`agent/app/policy.py`），不交給 LLM：L0 唯讀自動；L1 可逆低風險自動（2 次/10 分鐘、必須 Verify）；L2 需 Operator；L3 只產 incident bundle。

與計畫的差異：`agent/app/` 採扁平模組（ports、adapters、tools、llm、loop…）以求精簡；cooldown 以「頻率限制」取代。
