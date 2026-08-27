"""Pikafish UCI/UCCI 行程與序列化任務派送。不依賴 pygame。"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from . import paths


DEFAULT_MOVETIME_MS = 700
DEFAULT_EVAL_MOVETIME_MS = 250
INFINITE_SEARCH_MAX_WAIT_SEC = 2.0


@dataclass
class EngineTask:
    """引擎工作項目。之後加欄位只需給預設值，不必改 submit／loop 解包。"""
    req_id: int
    kind: str
    fen: str
    movetime_ms: int | None = None
    depth: int | None = None
    max_wait_sec: float | None = None


@dataclass
class EngineResult:
    """引擎工作結果。"""
    req_id: int
    kind: str
    fen: str
    status: str
    payload: object


class PikafishEngine:
    """以 UCI/UCCI 指令驅動 Pikafish。"""
    def __init__(self, engine_path=None):
        self.engine_path = engine_path or self.find_engine_path()
        self.process = None
        self.queue = queue.Queue()
        self.reader_thread = None

    def find_engine_path(self):
        candidates = []
        env_path = os.environ.get("PIKAFISH_PATH", "").strip()
        if env_path:
            candidates.append(env_path)

        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        onedrive_desktop = os.path.join(home, "OneDrive", "Desktop")

        for base in paths.get_runtime_search_dirs():
            candidates.extend([
                os.path.join(base, "pikafish.exe"),
                os.path.join(base, "pikafish"),
                os.path.join(base, "engines", "pikafish.exe"),
                os.path.join(base, "engines", "pikafish"),
                os.path.join(base, "Pikafish", "pikafish.exe"),
                os.path.join(base, "Pikafish", "pikafish"),
            ])
            # macOS：常見解壓資料夾命名
            if sys.platform == "darwin":
                candidates.extend([
                    os.path.join(base, "pikafish-macos"),
                    os.path.join(base, "pikafish_mac"),
                    os.path.join(base, "engines", "pikafish-macos"),
                ])

        candidates.extend([
            os.path.join(desktop, "pikafish.exe"),
            os.path.join(desktop, "pikafish"),
            os.path.join(onedrive_desktop, "pikafish.exe"),
            os.path.join(onedrive_desktop, "pikafish"),
        ])
        if sys.platform == "darwin":
            candidates.extend([
                os.path.join(desktop, "pikafish"),
                os.path.join(home, "bin", "pikafish"),
                "/usr/local/bin/pikafish",
                "/opt/homebrew/bin/pikafish",
            ])
        for path in candidates:
            if path and os.path.isfile(path) and os.access(path, os.X_OK if sys.platform != "win32" else os.F_OK):
                # Windows 不強制 X_OK；Unix 需可執行
                if sys.platform == "win32" or os.access(path, os.X_OK):
                    return path
                # 存在但尚未 chmod +x 的 mac/linux 二進位仍回傳，讓後續錯誤較明確
                if sys.platform != "win32" and os.path.isfile(path):
                    return path
        for path in candidates:
            if path and os.path.exists(path):
                return path
        # 找不到時回傳預設，讓錯誤訊息更直接
        return candidates[0] if candidates else "pikafish"

    def _reader(self):
        # 使用本地 proc 參考，避免 stop() 將 self.process 置 None 時 race 崩潰
        while True:
            proc = self.process
            if proc is None:
                break
            try:
                stdout = proc.stdout
                if stdout is None:
                    break
                line = stdout.readline()
            except Exception:
                break
            if not line:
                break
            try:
                self.queue.put(line.strip())
            except Exception:
                break

    def _format_start_error(self, message, startup_lines):
        details = [f"{message} (path={self.engine_path})"]
        if startup_lines:
            details.append("輸出=" + " | ".join(startup_lines[-8:]))
        return "；".join(details)

    def _send(self, cmd):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Pikafish process is not running")
        self.process.stdin.write(cmd + "\n")
        self.process.stdin.flush()

    def _wait_for(self, predicate, timeout_sec, seen_lines=None):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            remain = max(0.01, deadline - time.time())
            try:
                line = self.queue.get(timeout=remain)
            except queue.Empty:
                continue
            if seen_lines is not None:
                seen_lines.append(line)
            if predicate(line):
                return line
        return None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        # 握手任一階段失敗都必須 stop()，避免遺留 pikafish.exe / reader thread
        try:
            engine_cwd = None
            if os.path.isabs(self.engine_path):
                engine_cwd = os.path.dirname(self.engine_path) or None
            creationflags = 0
            startupinfo = None
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            self.process = subprocess.Popen(
                [self.engine_path],
                cwd=engine_cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            self.reader_thread = threading.Thread(target=self._reader, daemon=True)
            self.reader_thread.start()

            startup_lines = []
            self._send("uci")
            if not self._wait_for(lambda s: s == "uciok", 5, startup_lines):
                raise RuntimeError(self._format_start_error("Pikafish 啟動失敗：沒有收到 uciok", startup_lines))
            self._send("isready")
            if not self._wait_for(lambda s: s == "readyok", 5, startup_lines):
                raise RuntimeError(self._format_start_error("Pikafish 啟動失敗：沒有收到 readyok", startup_lines))
            self._send("ucinewgame")
            self._send("isready")
            if not self._wait_for(lambda s: s == "readyok", 5, startup_lines):
                raise RuntimeError(self._format_start_error("Pikafish 啟動失敗：ucinewgame 後沒有 readyok", startup_lines))
        except Exception:
            try:
                self.stop()
            except Exception:
                pass
            raise

    def _build_go_command(self, movetime_ms=None, depth=None):
        parts = []
        if isinstance(depth, int) and depth > 0:
            parts.extend(["depth", str(depth)])
        if movetime_ms is not None and movetime_ms > 0:
            parts.extend(["movetime", str(int(movetime_ms))])
        if parts:
            return "go " + " ".join(parts)
        return "go infinite"

    def bestmove(self, fen, movetime_ms=DEFAULT_MOVETIME_MS, depth=None, max_wait_sec=None):
        self._drain_queue()
        self._send(f"position fen {fen}")
        go_cmd = self._build_go_command(movetime_ms, depth)
        self._send(go_cmd)

        if max_wait_sec is None:
            if movetime_ms is not None and movetime_ms > 0:
                max_wait_sec = max(1.2, movetime_ms / 1000 + 1.0)
            else:
                max_wait_sec = INFINITE_SEARCH_MAX_WAIT_SEC

        line = self._wait_for(lambda s: s.startswith("bestmove "), max_wait_sec)
        if not line and go_cmd == "go infinite":
            try:
                self._send("stop")
            except Exception:
                pass
            line = self._wait_for(lambda s: s.startswith("bestmove "), 2)
        if not line:
            return None
        parts = line.split()
        if len(parts) < 2 or parts[1] == "(none)":
            return None
        return parts[1]

    def _drain_queue(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _parse_score_line(self, line):
        parts = line.split()
        for i in range(len(parts) - 2):
            if parts[i] != "score":
                continue
            score_type = parts[i + 1]
            score_val = parts[i + 2]
            if score_type in ("cp", "mate") and score_val.lstrip("-").isdigit():
                return score_type, int(score_val)
        return None

    def analyse_score(self, fen, movetime_ms=DEFAULT_EVAL_MOVETIME_MS):
        full = self.analyse_full(fen, movetime_ms=movetime_ms)
        return full["score_type"], full["score_value"]

    def analyse_full(self, fen, movetime_ms=DEFAULT_EVAL_MOVETIME_MS):
        """分析局面：分數 + 最佳著 + 主變例 PV。"""
        self._drain_queue()
        self._send(f"position fen {fen}")
        self._send(f"go movetime {int(movetime_ms)}")

        latest = ("cp", 0)
        best_pv = []
        bestmove = None
        deadline = time.time() + max(2, movetime_ms / 1000 + 2)
        while time.time() < deadline:
            remain = max(0.01, deadline - time.time())
            try:
                line = self.queue.get(timeout=remain)
            except queue.Empty:
                continue

            if line.startswith("info "):
                parsed = self._parse_score_line(line)
                if parsed:
                    latest = parsed
                parts = line.split()
                if "pv" in parts:
                    pi = parts.index("pv")
                    cand = parts[pi + 1:]
                    if cand:
                        best_pv = cand
            elif line.startswith("bestmove "):
                sp = line.split()
                if len(sp) >= 2 and sp[1] != "(none)":
                    bestmove = sp[1]
                break

        return {
            "score_type": latest[0],
            "score_value": latest[1],
            "bestmove": bestmove,
            "pv": best_pv,
        }

    def stop(self):
        if not self.process:
            return
        proc = self.process
        reader_thread = self.reader_thread
        try:
            if proc.poll() is None:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        if reader_thread and reader_thread.is_alive():
            reader_thread.join(timeout=0.5)
        self.process = None
        self.reader_thread = None


class EngineDispatcher:
    """單一引擎工作器：序列化處理 AI/評估/建議任務。"""
    def __init__(self, engine_path=None):
        self.engine_path = engine_path
        self.engine = None
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.engine = PikafishEngine(self.engine_path)
        try:
            self.engine.start()
        except Exception:
            # 握手失敗時 engine.stop() 已在 start() 內呼叫；此處再保險清理
            try:
                self.engine.stop()
            except Exception:
                pass
            self.engine = None
            raise
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def _handle_task(self, task):
        if task is None:
            return
        try:
            if task.kind == "bestmove":
                payload = self.engine.bestmove(
                    task.fen, task.movetime_ms, depth=task.depth, max_wait_sec=task.max_wait_sec
                )
            elif task.kind == "analyse":
                payload = self.engine.analyse_score(task.fen, task.movetime_ms)
            elif task.kind == "analyse_full":
                payload = self.engine.analyse_full(task.fen, task.movetime_ms)
            else:
                raise RuntimeError(f"unknown task kind: {task.kind}")
            self.result_queue.put(EngineResult(
                req_id=task.req_id,
                kind=task.kind,
                fen=task.fen,
                status="ok",
                payload=payload,
            ))
        except Exception as ex:
            self.result_queue.put(EngineResult(
                req_id=task.req_id,
                kind=task.kind,
                fen=task.fen,
                status="err",
                payload=str(ex),
            ))

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                task = self.task_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._handle_task(task)

    def submit(self, req_id, kind, fen, movetime_ms=None, depth=None, max_wait_sec=None):
        self.task_queue.put(EngineTask(
            req_id=req_id,
            kind=kind,
            fen=fen,
            movetime_ms=movetime_ms,
            depth=depth,
            max_wait_sec=max_wait_sec,
        ))

    def get_result_nowait(self):
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self.stop_event.set()
        try:
            self.task_queue.put_nowait(None)
        except Exception:
            pass
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=0.2)
        if self.engine:
            self.engine.stop()
        self.worker = None
        self.engine = None
