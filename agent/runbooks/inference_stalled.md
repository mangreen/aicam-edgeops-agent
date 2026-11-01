# inference_stalled 推論 pipeline 卡死
症狀：FPS 歸零但串流連線正常；log 出現 "inference worker stalled"；infer span 逾時。
處置（L1，可自動）：restart_pipeline，Verify 指標恢復。10 分鐘內最多 2 次，避免重啟風暴。
升級：重啟 2 次仍失敗 → Operator 檢查主機資源；仍無法 → 遠端工程師。
