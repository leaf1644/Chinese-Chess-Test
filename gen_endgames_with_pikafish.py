"""
用 Pikafish 驗證／篩選殘局 FEN。關卡唯一來源是 endgames.json。

用法：
  python gen_endgames_with_pikafish.py              # 只分析、印結果
  python gen_endgames_with_pikafish.py --write      # 把引擎解／評估寫回 JSON
  python gen_endgames_with_pikafish.py --movetime 1500
  python gen_endgames_with_pikafish.py --write --replace-ids  # 連難度也依殺步調整
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import chess as app


def analyse_level(engine: app.PikafishEngine, fen: str, movetime_ms: int):
    score_type, score_val = engine.analyse_score(fen, movetime_ms=movetime_ms)
    best = engine.bestmove(fen, movetime_ms=max(400, movetime_ms // 2))
    return score_type, score_val, best


def is_winning(score_type: str, score_val: int, min_mate: int = 1) -> bool:
    """紅先局面：mate>0 或 cp 明顯優勢。

    min_mate：拒絕「一步殺」這類過於送分的題（預設允許 mate>=1；
    寫檔時對 difficulty>=2 會要求 mate>=3 或僅 cp 優勢）。
    """
    if score_type == "mate":
        return score_val >= min_mate
    if score_type == "cp":
        return score_val >= 300  # 約 +3 兵以上視為可勝題
    return False


def validate_candidate(level: dict):
    board = app.XiangqiBoard(game_mode=app.MODE_ENDGAME, fen=level["fen"])
    ok, reason = app.validate_endgame_start_position(board)
    return ok, reason, board.to_fen()


def load_catalog(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_catalog(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def apply_engine_fields(level: dict, st: str, sv: int, bm: str | None, *, retune_difficulty: bool) -> dict:
    """把引擎結果寫進關卡副本；不改 fen／title／section／hint。"""
    lv = dict(level)
    lv["solution"] = [bm] if bm else []
    lv["engine_eval"] = f"{st}:{sv}"
    if st == "mate" and sv > 0:
        lv["max_player_moves"] = max(lv.get("max_player_moves", 30), sv * 2 + 10)
        if retune_difficulty:
            if sv <= 4:
                lv["difficulty"] = max(1, min(lv.get("difficulty", 2), 2))
            elif sv <= 10:
                lv["difficulty"] = max(lv.get("difficulty", 2), 2)
            else:
                lv["difficulty"] = max(lv.get("difficulty", 3), 3)
    return lv


def main():
    parser = argparse.ArgumentParser(description="Pikafish 殘局驗證／寫入（來源：endgames.json）")
    parser.add_argument("--write", action="store_true", help="將通過關卡的引擎解／評估寫回 endgames.json")
    parser.add_argument("--movetime", type=int, default=1200, help="每局面分析毫秒（預設 1200）")
    parser.add_argument(
        "--replace-ids",
        action="store_true",
        help="寫回時一併依殺步長短調整 difficulty",
    )
    args = parser.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    catalog_path = os.path.join(root, "endgames.json")
    if not os.path.isfile(catalog_path):
        print(f"找不到 {catalog_path}")
        return 1

    data = load_catalog(catalog_path)
    levels = data.get("levels", [])
    if not isinstance(levels, list) or not levels:
        print("endgames.json 沒有 levels")
        return 1

    print(f"啟動 Pikafish… (movetime={args.movetime}ms)")
    engine = app.PikafishEngine()
    engine.start()

    passed = []
    rejected = []

    try:
        print("\n=== 關卡（endgames.json）===")
        for lv in levels:
            ok, reason, canon = validate_candidate(lv)
            if not ok:
                rejected.append((lv, f"規則：{reason}"))
                print(f"  [REJECT] {lv['id']} {lv.get('title')}: {reason}")
                continue

            st, sv, bm = analyse_level(engine, lv["fen"], args.movetime)
            min_mate = 1 if lv.get("difficulty", 1) <= 1 else 3
            win = is_winning(st, sv, min_mate=min_mate)
            mate_info = ""
            if st == "mate" and sv > 0:
                mate_info = f" mate in {sv}"
            if st == "mate" and 0 < sv < min_mate:
                rejected.append((lv, f"殺步太短 mate:{sv}（需要 >= {min_mate}）"))
                print(f"  [REJECT] {lv['id']} {lv.get('title')}: mate too short ({sv}) best={bm}")
                continue
            if not win:
                rejected.append((lv, f"引擎不認為紅勝 ({st}:{sv})"))
                print(f"  [WARN] {lv['id']} {lv.get('title')}: score={st}:{sv} best={bm}")
                continue

            updated = apply_engine_fields(
                lv, st, sv, bm, retune_difficulty=args.replace_ids
            )
            passed.append(updated)
            print(
                f"  [PASS] {lv['id']} {lv.get('title')}: score={st}:{sv}{mate_info} "
                f"best={bm} fen={canon}"
            )
    finally:
        engine.stop()

    print(f"\n通過 {len(passed)} / 關卡 {len(levels)}；未過 {len(rejected)}")

    if not args.write:
        print("（未寫檔；加上 --write 才會更新 endgames.json 的 solution／engine_eval）")
        return 0 if passed else 1

    by_id = {lv["id"]: lv for lv in levels}
    for lv in passed:
        by_id[lv["id"]] = lv
    data["levels"] = sorted(by_id.values(), key=lambda x: x["id"])
    data["version"] = max(int(data.get("version", 2)), 2)
    if "schema_notes" not in data:
        data["schema_notes"] = {}
    data["schema_notes"]["engine"] = (
        "以 validate_endgame_start_position + Pikafish 驗證後收錄；solution 為引擎建議第一步（UCCI）。"
    )
    write_catalog(catalog_path, data)
    print(f"已寫入 {catalog_path}，共 {len(data['levels'])} 關。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
