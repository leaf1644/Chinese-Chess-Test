"""文字折行與棋鐘格式。"""
from __future__ import annotations

def wrap_text_by_width(text, font, max_width):
    """依像素寬度折行（中英混排按字元切）。"""
    if not text:
        return []
    if max_width <= 8:
        return [text]
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def format_clock_ms(ms):
    """毫秒 → mm:ss 顯示。"""
    ms = max(0, int(ms))
    total_sec = (ms + 999) // 1000
    m, s = divmod(total_sec, 60)
    return f"{m:02d}:{s:02d}"
