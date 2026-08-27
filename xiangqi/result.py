"""終局結果型別。不依賴 pygame。"""
from __future__ import annotations

from dataclasses import dataclass


class ResultKind:
    CHECKMATE = "checkmate"          # 將死／困斃
    TIMEOUT = "timeout"              # 超時
    AGREE_DRAW = "agree_draw"        # 協議和
    REPEAT_POSITION = "repeat_position"
    REPEAT_MOVES = "repeat_moves"
    NO_CROSSING = "no_crossing"
    LONG_CHECK = "long_check"
    LONG_CHASE = "long_chase"


@dataclass
class GameResult:
    kind: str
    winner: str | None = None
    message: str = ""

    @property
    def is_draw(self) -> bool:
        return self.winner is None
