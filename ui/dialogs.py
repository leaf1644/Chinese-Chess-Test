"""簡易文字輸入（Tk）。"""
from __future__ import annotations

def prompt_text_input(title, prompt, initial=""):
    """彈出輸入框（支援中文 IME），回傳字串或 None（取消）。"""
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            result = simpledialog.askstring(title, prompt, initialvalue=initial, parent=root)
        finally:
            root.destroy()
        if result is None:
            return None
        result = result.strip()
        return result if result else None
    except Exception:
        return None

