"""中國象棋相容入口：規則在 xiangqi，畫面在 ui。"""
from __future__ import annotations

from xiangqi.board import (  # noqa: F401
    Move,
    Piece,
    XiangqiBoard,
    apply_ucci_move,
    board_to_ucci,
    classify_move_quality,
    count_pieces_by_side_and_name,
    create_empty_xiangqi_board,
    is_legal_piece_square,
    piece_type_from_name,
    score_to_cp,
    ucci_pv_to_chinese,
    ucci_to_board,
    ucci_to_chinese_notation,
    validate_editor_position,
    validate_endgame_piece_placements,
    validate_endgame_start_position,
    validate_legal_position,
    validate_piece_counts,
)
from xiangqi.constants import (  # noqa: F401
    AI_DELAY_SEC,
    AI_DIFFICULTY_PRESETS,
    AI_SUGGEST_MOVETIME_MS,
    ANALYSIS_MOVETIME_MS,
    BLACK,
    CUSTOM_POSITIONS_FILE_NAME,
    CUSTOM_POSITIONS_LEGACY_NAME,
    ENDGAME_AI_DEPTH,
    ENDGAME_AI_MAX_WAIT_SEC,
    ENDGAME_AI_MOVETIME_MS,
    ENDGAME_DIFF_GROUPS,
    ENDGAME_PROGRESS_FILE_NAME,
    ENDGAME_SECTION_CHALLENGE,
    ENDGAME_SECTION_FORMULA,
    ENDGAMES_FILE_NAME,
    EDITOR_PALETTE_BLACK,
    EDITOR_PALETTE_RED,
    FEN_TO_PIECE,
    MODE_AI,
    MODE_EDITOR,
    MODE_EDITOR_LIB,
    MODE_ENDGAME,
    MODE_ENDGAME_DIFF,
    MODE_ENDGAME_LEVELS,
    MODE_MENU,
    MODE_PVP,
    PIECE_MAX_COUNT,
    PIECE_TO_FEN,
    RED,
    SAVE_FILE_NAME,
    SIDE_RGB,
    parse_side,
    side_rgb,
    TIME_CONTROL_PRESETS,
    UCCI_FILES,
)
from xiangqi.result import GameResult, ResultKind  # noqa: F401
from xiangqi.endgame import (  # noqa: F401
    is_endgame_unlocked,
    is_unlocked_in_sequence,
    load_endgame_progress,
    load_endgames_catalog,
    save_endgame_progress,
)
from xiangqi.engine import (  # noqa: F401
    DEFAULT_EVAL_MOVETIME_MS as AI_EVAL_MOVETIME_MS,
    DEFAULT_MOVETIME_MS as AI_MOVETIME_MS,
    INFINITE_SEARCH_MAX_WAIT_SEC as AI_INFINITE_SEARCH_MAX_WAIT_SEC,
    EngineDispatcher,
    EngineResult,
    EngineTask,
    PikafishEngine,
)
from xiangqi.i18n import (  # noqa: F401
    LANG_HANS,
    LANG_HANT,
    LANGUAGE_FILE_NAME,
    UI_STRINGS,
    ai_difficulty_display,
    diff_group_label,
    difficulty_label,
    get_lang,
    load_language_pref,
    save_language_pref,
    section_label,
    set_language,
    t,
    time_control_label,
)
from xiangqi.paths import (  # noqa: F401
    APP_NAME,
    find_data_file,
    get_runtime_search_dirs,
    get_user_data_dir,
    get_user_data_path,
)
from xiangqi.persist import load_custom_positions, save_custom_positions  # noqa: F401


def main():
    """啟動 pygame 主迴圈（延遲載入 ui，讓規則測試不必綁顯示器）。"""
    from ui.app import main as _main
    _main()


if __name__ == "__main__":
    main()
