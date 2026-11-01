---
name: camera-troubleshoot
description: 攝影機／推論 pipeline 故障排除流程
tools: query_logs, query_metrics, restart_pipeline, reconnect_stream
---
排除攝影機或推論故障時：先查近期 logs 與 metrics 確認症狀；FPS 歸零但串流正常 → 重啟 pipeline；串流中斷 → 先重連，失敗兩次即請 Operator 檢查電源、PoE、網路線。每個修復動作後必須重查指標（Verify）。
