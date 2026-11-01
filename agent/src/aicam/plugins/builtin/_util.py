import time


def _ago(ts): return time.strftime("%m/%d %H:%M", time.localtime(ts))
def _int(v): return {"type": "integer", "description": v}
def _str(v): return {"type": "string", "description": v}
