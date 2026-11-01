"""內建工具共用的小工具（時間格式、schema 片段）。"""
import time


def _ago(ts): return time.strftime("%m/%d %H:%M", time.localtime(ts))
def _int(v): return {"type": "integer", "description": v}
def _str(v): return {"type": "string", "description": v}
