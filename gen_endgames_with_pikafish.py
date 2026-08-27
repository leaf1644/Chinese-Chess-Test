"""
用 Pikafish 驗證／篩選殘局 FEN，並可寫入 endgames.json。

用法：
  python gen_endgames_with_pikafish.py              # 只分析、印結果
  python gen_endgames_with_pikafish.py --write      # 通過的候補關卡寫入 endgames.json
  python gen_endgames_with_pikafish.py --movetime 1500
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 避免 chess.py 以外還要 pygame display（import 時只 init 字型等即可）
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import chess as app


# 經典／教學向候補殘局（與 endgames.json 中 eg_005+ 同步；紅先、開局不可已被將軍）
# 重新產生：python gen_endgames_with_pikafish.py --write --replace-ids
CANDIDATES = [
    {
        "id": "eg_005",
        "title": "單車擒士",
        "difficulty": 2,
        "category": "殺法",
        "player_side": "red",
        "fen": "3ak4/9/9/9/9/9/9/9/9/R4K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 45,
        "hint": "士會護將，先用車趕士離開或逼將離宮，再配合帥控制中線。",
        "unlock_after": "eg_002",
    },
    {
        "id": "eg_006",
        "title": "雙馬攻雙士",
        "difficulty": 4,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/3a1a3/9/9/9/9/2N6/2N6/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 50,
        "hint": "雙馬配合帥逐步壓縮，注意雙士聯防，尋找臥槽或掛角機會。",
        "unlock_after": "eg_003",
    },
    {
        "id": "eg_007",
        "title": "馬後炮",
        "difficulty": 1,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/4N4/9/9/9/9/9/9/3C1K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 5,
        "hint": "馬已就位。把炮移到中線馬的後方，形成「馬後炮」一步殺。",
        "unlock_after": "eg_001",
    },
    {
        "id": "eg_008",
        "title": "雙炮攻士",
        "difficulty": 3,
        "category": "殺法",
        "player_side": "red",
        "fen": "3ak4/9/9/9/9/9/9/9/2C1C4/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 45,
        "hint": "雙炮重疊或分控兩翼，逼士離開後再悶殺／空頭炮。",
        "unlock_after": "eg_004",
    },
    {
        "id": "eg_009",
        "title": "炮兵破士",
        "difficulty": 3,
        "category": "殺法",
        "player_side": "red",
        "fen": "3ak4/9/9/9/4P4/9/9/9/3C5/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 50,
        "hint": "兵限制將／士活動，炮找架炮點或底線抽將。",
        "unlock_after": "eg_004",
    },
    {
        "id": "eg_010",
        "title": "車炮攻雙士",
        "difficulty": 3,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/3a1a3/9/9/9/9/9/2C6/3R1K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 45,
        "hint": "車炮配合牽制雙士，注意不要讓黑將輕易出宮脫身。",
        "unlock_after": "eg_005",
    },
    {
        "id": "eg_011",
        "title": "雙兵破雙士",
        "difficulty": 3,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/3a1a3/9/3P1P3/9/9/9/9/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 55,
        "hint": "雙兵聯防推進，先破士或逼將離宮，忌孤兵被士吃掉。",
        "unlock_after": "eg_004",
    },
    {
        "id": "eg_012",
        "title": "馬擒單士",
        "difficulty": 4,
        "category": "殺法",
        "player_side": "red",
        "fen": "3ak4/9/9/9/9/9/9/9/3N5/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 60,
        "hint": "僅一馬需與帥緊密配合，先逼士離將或吃士再做殺。",
        "unlock_after": "eg_005",
    },
    {
        "id": "eg_013",
        "title": "單馬擒將",
        "difficulty": 4,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/9/9/9/9/9/9/3N5/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 70,
        "hint": "單馬需帥緊密配合，把將逼到邊角再做殺。過程較長，耐心運子。",
        "unlock_after": "eg_006",
    },
    {
        "id": "eg_014",
        "title": "馬炮破雙士",
        "difficulty": 3,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/3a1a3/9/9/9/9/2N6/4C4/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 55,
        "hint": "先破士再做殺；注意雙士聯防，用馬騰挪打開炮路。",
        "unlock_after": "eg_007",
    },
    {
        "id": "eg_015",
        "title": "三兵破士象全",
        "difficulty": 4,
        "category": "殺法",
        "player_side": "red",
        "fen": "2bakab2/9/9/2P1P1P2/9/9/9/9/9/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 70,
        "hint": "黑方士象全防守堅固。三兵連營推進，勿急於送吃；先破象或逼士再做殺。開局一步吃不到對方子，耐心運兵。",
        "unlock_after": "eg_011",
    },
    {
        "id": "eg_016",
        "title": "炮士勝單將",
        "difficulty": 4,
        "category": "殺法",
        "player_side": "red",
        "fen": "4k4/9/9/9/9/9/9/3A5/3C5/5K3 w - - 0 1",
        "goal": "checkmate",
        "max_player_moves": 60,
        "hint": "用仕作炮架，把將逼到死角；注意士的保護與露帥。",
        "unlock_after": "eg_009",
    },
]


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


def main():
    parser = argparse.ArgumentParser(description="Pikafish 殘局驗證／寫入")
    parser.add_argument("--write", action="store_true", help="將通過的候補寫入 endgames.json")
    parser.add_argument("--movetime", type=int, default=1200, help="每局面分析毫秒（預設 1200）")
    parser.add_argument("--keep-existing", action="store_true", default=True,
                        help="保留既有關卡（預設）")
    parser.add_argument("--replace-ids", action="store_true",
                        help="同 id 則以新候補覆寫")
    args = parser.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    catalog_path = os.path.join(root, "endgames.json")

    print(f"啟動 Pikafish… (movetime={args.movetime}ms)")
    engine = app.PikafishEngine()
    engine.start()

    passed = []
    rejected = []

    try:
        # 也順便驗證現有關卡
        if os.path.exists(catalog_path):
            existing = load_catalog(catalog_path)
            print("\n=== 現有關卡 ===")
            for lv in existing.get("levels", []):
                ok, reason, _ = validate_candidate(lv)
                st, sv, bm = analyse_level(engine, lv["fen"], args.movetime)
                win = is_winning(st, sv)
                mark = "OK" if ok and win else "WARN"
                print(f"  [{mark}] {lv['id']} {lv['title']}: valid={ok} "
                      f"score={st}:{sv} best={bm} {'' if ok else reason}")

        print("\n=== 候補關卡（Pikafish）===")
        for lv in CANDIDATES:
            ok, reason, canon = validate_candidate(lv)
            if not ok:
                rejected.append((lv, f"規則：{reason}"))
                print(f"  [REJECT] {lv['id']} {lv['title']}: {reason}")
                continue

            st, sv, bm = analyse_level(engine, lv["fen"], args.movetime)
            # 入門可接受短殺；初級以上避免一步／兩步送分題
            min_mate = 1 if lv.get("difficulty", 1) <= 1 else 3
            win = is_winning(st, sv, min_mate=min_mate)
            mate_info = ""
            lv = dict(lv)
            if st == "mate" and sv > 0:
                mate_info = f" mate in {sv}"
                lv["max_player_moves"] = max(lv.get("max_player_moves", 30), sv * 2 + 10)
                if sv <= 4:
                    lv["difficulty"] = max(1, min(lv.get("difficulty", 2), 2))
                elif sv <= 10:
                    lv["difficulty"] = max(lv.get("difficulty", 2), 2)
                else:
                    lv["difficulty"] = max(lv.get("difficulty", 3), 3)
                # 不把引擎步數寫進玩家提示（避免劇透），只印在終端
            if st == "mate" and 0 < sv < min_mate:
                rejected.append((lv, f"殺步太短 mate:{sv}（需要 >= {min_mate}）"))
                print(f"  [REJECT] {lv['id']} {lv['title']}: mate too short ({sv}) best={bm}")
                continue

            if not win:
                rejected.append((lv, f"引擎不認為紅勝 ({st}:{sv})"))
                print(f"  [REJECT] {lv['id']} {lv['title']}: score={st}:{sv} best={bm}")
                continue

            lv["solution"] = [bm] if bm else []
            # 記錄引擎評估供日後維護（遊戲可忽略未知欄位）
            lv["engine_eval"] = f"{st}:{sv}"
            passed.append(lv)
            print(f"  [PASS] {lv['id']} {lv['title']}: score={st}:{sv}{mate_info} "
                  f"best={bm} fen={canon}")
    finally:
        engine.stop()

    print(f"\n通過 {len(passed)} / 候補 {len(CANDIDATES)}；拒絕 {len(rejected)}")

    if not args.write:
        print("（未寫檔；加上 --write 才會更新 endgames.json）")
        return 0 if passed else 1

    data = load_catalog(catalog_path) if os.path.exists(catalog_path) else {
        "version": 2,
        "schema_notes": {
            "rule": "開局雙方皆不可被將軍、不可將帥照面；過關條件僅為將死對手（含困斃）。",
            "fen": "與 app to_fen() 相同：第 1 列為黑方底線(y=0)，最後一列為紅方底線(y=9)；w=紅走 b=黑走",
            "engine": "候補局面經 Pikafish 評估為紅方優勢／可殺後寫入。",
        },
        "levels": [],
    }

    by_id = {lv["id"]: lv for lv in data.get("levels", [])}
    for lv in passed:
        if lv["id"] in by_id and not args.replace_ids:
            # 預設：已有 id 則跳過，避免覆寫玩家已通關進度對應關
            print(f"  skip existing id {lv['id']}（用 --replace-ids 可覆寫）")
            continue
        by_id[lv["id"]] = lv

    # 維持 id 排序
    levels = sorted(by_id.values(), key=lambda x: x["id"])
    data["levels"] = levels
    data["version"] = max(int(data.get("version", 2)), 2)
    if "schema_notes" not in data:
        data["schema_notes"] = {}
    data["schema_notes"]["engine"] = "部分關卡經 Pikafish 評估為紅勝後收錄。"

    write_catalog(catalog_path, data)
    print(f"已寫入 {catalog_path}，共 {len(levels)} 關。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
