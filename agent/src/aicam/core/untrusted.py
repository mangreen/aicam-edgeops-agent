"""不可信資料隔離：log、網頁等外部內容進入 LLM 前一律包上標記，並中和標記本身的偽造。"""
import re


def wrap(source: str, text: str) -> str:
    text = re.sub(r"</?\s*untrusted[^>]*>", "[已移除偽造標記]", text, flags=re.I)
    return f'<untrusted source="{source}">\n{text}\n</untrusted>'
