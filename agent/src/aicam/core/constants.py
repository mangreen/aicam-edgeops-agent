"""領域詞彙與跨模組常數。"""
KIND_ZH = {"inference_stalled": "推論 pipeline 卡死", "camera_no_signal": "攝影機無訊號", "detection_drop": "偵測數驟降"}
CAUSE = {"inference_stalled": "推論 worker 卡死（FPS 歸零但串流正常）",
         "camera_no_signal": "攝影機串流中斷，疑似電源／PoE／網路線問題",
         "detection_drop": "近期設定變更導致偵測數驟降"}
HINT = {"camera_no_signal": "請檢查攝影機電源、PoE 與網路線",
        "inference_stalled": "請檢查邊緣主機資源與推論服務",
        "detection_drop": "請確認近期設定變更並檢視 ROI／門檻"}
