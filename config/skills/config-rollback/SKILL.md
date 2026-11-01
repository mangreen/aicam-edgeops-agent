---
name: config-rollback
description: 設定變更與 rollback 流程
tools: list_versions, diff_versions, rollback_version
---
偵測數驟降且近期有他人變更時：用 diff_versions 對照變更內容，並比較變更前後指標；有相關性證據才可建議 rollback 上一版（附 diff 與證據）。Rollback 後必須 Verify，失敗不得重複 rollback，改升級 Operator。
