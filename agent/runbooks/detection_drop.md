# detection_drop 偵測數驟降
症狀：FPS 正常、串流連線正常，但 detections_per_min 驟降；log 出現 "vehicle detections dropped"。
常見原因：近期設定變更（ROI 過小或錯位、門檻錯誤、模型版本）。
處置：先 list_versions / diff_versions 對照異常起點；若與近期變更相關，rollback 到上一版（附 diff 與證據），再 Verify。
不重複 rollback；Verify 失敗 → 升級 Operator。
