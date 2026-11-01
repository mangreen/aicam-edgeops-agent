# camera_no_signal 攝影機無訊號
症狀：stream_connected 為 0；log 出現 "stream disconnected"；capture span 逾時。
處置（L1）：reconnect_stream。若重連失敗，通常是實體問題（電源、PoE 供電、網路線、switch 埠）。
升級：重連 2 次失敗 → Operator 現場檢查電源／PoE／網路線；無法處理 → 遠端工程師（可能需更換 switch 埠或攝影機）。
