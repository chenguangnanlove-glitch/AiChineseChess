"""15×15 五子棋，自由规则。

无禁手：长连、三三、四四都允许。横、竖、两条斜线上连续五个或更多同色棋子即获胜。
满盘仍无人达成五连则为和棋。这不是职业连珠 / 连珠禁手规则。

坐标：列 A–O 从左到右，行 1–15 从上到下。落子写法如 H8。
棋盘串：15 行用 / 分隔，黑子 X、白子 O、空点 . 。
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

SIZE = 15
EMPTY = "."
BLACK_STONE = "X"
WHITE_STONE = "O"
COLUMNS = "ABCDEFGHIJKLMNO"


def _normalize_width(text: str) -> str:
    if not text:
        return ""
    trans = {}
    for i in range(26):
        trans[ord("Ａ") + i] = ord("A") + i
        trans[ord("ａ") + i] = ord("A") + i
    for i in range(10):
        trans[ord("０") + i] = ord("0") + i
    trans[ord("：")] = ord(":")
    trans[ord("．")] = ord(".")
    return text.translate(trans)


class GomokuGame:
    """五子棋对局。黑棋先手。"""

    game_type = "gomoku"

    def __init__(self):
        self.board = [[EMPTY for _ in range(SIZE)] for _ in range(SIZE)]
        self.move_history: List[dict] = []
        self.current_player = "black"
        self.start_time = time.time()

    def side_label(self, color: str) -> str:
        return "黑棋" if color == "black" else "白棋"

    def stone_for(self, color: str) -> str:
        return BLACK_STONE if color == "black" else WHITE_STONE

    @staticmethod
    def opponent(color: str) -> str:
        return "white" if color == "black" else "black"

    def rules_summary(self) -> str:
        return (
            "五子棋 15×15 自由规则：无禁手；横、竖、斜连续五子或以上即获胜；"
            "下满棋盘仍没有五连则和棋。不是职业连珠禁手规则。"
        )

    def system_prompt(self) -> str:
        return (
            "你是五子棋棋手。这盘是 15×15 自由规则（无禁手，五连或以上获胜），"
            "不是中国象棋。不要使用象棋的四字坐标（例如 a0a1），只使用列 A–O、行 1–15 的落点，例如 H8。"
        )

    def init_board(self):
        self.board = [[EMPTY for _ in range(SIZE)] for _ in range(SIZE)]
        return self.board

    def reset(self):
        self.init_board()
        self.move_history = []
        self.current_player = "black"
        self.start_time = time.time()

    def get_board_state(self) -> str:
        return "/".join("".join(row) for row in self.board)

    def load_board_state(self, board_state: str, current_player: str = "black"):
        rows = (board_state or "").strip().split("/")
        if len(rows) != SIZE or any(len(r) != SIZE for r in rows):
            raise ValueError("五子棋棋盘应为 15 行、每行 15 格，用 / 分隔")
        allowed = {EMPTY, BLACK_STONE, WHITE_STONE}
        if any(ch not in allowed for row in rows for ch in row):
            raise ValueError("五子棋棋盘只能包含 X（黑）、O（白）和 .（空）")
        if current_player not in ("black", "white"):
            raise ValueError("五子棋执子方只能是 black 或 white")
        self.board = [list(r) for r in rows]
        self.current_player = current_player
        self.move_history = []

    def normalize_move(self, move_str: str) -> Optional[str]:
        text = _normalize_width(move_str or "").strip().upper().replace(" ", "")
        match = re.fullmatch(r"([A-O])(1[0-5]|[1-9])", text)
        if not match:
            return None
        return match.group(1) + match.group(2)

    def coord_to_pos(self, coord: str) -> Optional[Tuple[int, int]]:
        move = self.normalize_move(coord)
        if not move:
            return None
        col = COLUMNS.index(move[0])
        row = int(move[1:]) - 1
        if not (0 <= row < SIZE and 0 <= col < SIZE):
            return None
        return row, col

    def pos_to_coord(self, pos: Tuple[int, int]) -> str:
        row, col = pos
        return f"{COLUMNS[col]}{row + 1}"

    def get_legal_moves(self) -> List[str]:
        if self.is_game_over():
            return []
        moves = []
        for row in range(SIZE):
            for col in range(SIZE):
                if self.board[row][col] == EMPTY:
                    moves.append(self.pos_to_coord((row, col)))
        return moves

    def make_move(self, move_str: str) -> bool:
        if self.is_game_over():
            return False
        pos = self.coord_to_pos(move_str)
        if pos is None:
            return False
        row, col = pos
        if self.board[row][col] != EMPTY:
            return False
        stone = self.stone_for(self.current_player)
        self.board[row][col] = stone
        canonical = self.pos_to_coord(pos)
        self.move_history.append({
            "move": canonical,
            "row": row,
            "col": col,
            "player": self.current_player,
            "piece": stone,
            "timestamp": time.time(),
            "notation": f"{self.side_label(self.current_player)} {canonical}",
        })
        self.current_player = self.opponent(self.current_player)
        return True

    def _has_run(self, stone: str, need: int = 5) -> bool:
        directions = ((0, 1), (1, 0), (1, 1), (1, -1))
        for row in range(SIZE):
            for col in range(SIZE):
                if self.board[row][col] != stone:
                    continue
                for dr, dc in directions:
                    prev_r, prev_c = row - dr, col - dc
                    if 0 <= prev_r < SIZE and 0 <= prev_c < SIZE and self.board[prev_r][prev_c] == stone:
                        continue
                    count = 0
                    rr, cc = row, col
                    while 0 <= rr < SIZE and 0 <= cc < SIZE and self.board[rr][cc] == stone:
                        count += 1
                        rr += dr
                        cc += dc
                    if count >= need:
                        return True
        return False

    def _is_full(self) -> bool:
        return all(cell != EMPTY for row in self.board for cell in row)

    def winner_color(self) -> Optional[str]:
        black = self._has_run(BLACK_STONE, 5)
        white = self._has_run(WHITE_STONE, 5)
        if black and white:
            if self.move_history:
                return self.move_history[-1]["player"]
            return "black"
        if black:
            return "black"
        if white:
            return "white"
        return None

    def get_game_status(self) -> Dict:
        winner = self.winner_color()
        if winner:
            label = self.side_label(winner)
            return {
                "over": True,
                "winner": winner,
                "reason": "five",
                "message": f"{label}连成五子或以上，{label}获胜",
            }
        if self._is_full():
            return {
                "over": True,
                "winner": None,
                "reason": "full",
                "message": "棋盘已满，没有五连，和棋",
            }
        return {"over": False, "winner": None, "reason": "ongoing", "message": "对局进行中"}

    def is_game_over(self) -> bool:
        return self.get_game_status()["over"]

    def get_game_result(self) -> str:
        status = self.get_game_status()
        if not status["over"]:
            return "游戏进行中"
        if status["winner"] == "black":
            return "黑棋获胜"
        if status["winner"] == "white":
            return "白棋获胜"
        return "和棋"

    def format_board_display(self) -> str:
        header = "   " + " ".join(COLUMNS)
        lines = [header]
        for row in range(SIZE):
            cells = []
            for col in range(SIZE):
                stone = self.board[row][col]
                cells.append("●" if stone == BLACK_STONE else "○" if stone == WHITE_STONE else "·")
            lines.append(f"{row + 1:>2} " + " ".join(cells))
        return "\n".join(lines)

    def build_prompt(self, board_state: str, move_history: List[dict], legal_moves: List[str] = None,
                     retry_hint: str = None, strict_output: bool = False, **_ignored) -> str:
        history_parts = []
        for move in (move_history or [])[-10:]:
            who = "黑" if move.get("player") == "black" else "白"
            history_parts.append(f"{who}:{move.get('move', '')}")
        history = " ".join(history_parts) if history_parts else "空盘"
        legal_list = list(legal_moves or [])
        example = legal_list[0] if legal_list else "H8"
        side = self.side_label(self.current_player)
        prompt = f"""你正在下五子棋，执{side}。黑棋先手，现在已落 {len(move_history or [])} 子。请从合法落点中选一个空点。

规则：15×15 自由规则，无禁手。横、竖、两条斜线任意一条连成五子或更多同色棋子就获胜（超过五子也算赢）。这不是职业连珠，不要按禁手弃权。
坐标：列 A–O（从左到右），行 1–15（从上到下）。例如 H8 是第 H 列、第 8 行。不要使用中国象棋坐标（a0a1 这种四字走法在这里无效）。
棋盘：● 是黑棋，○ 是白棋，· 是空点。
{self.format_board_display()}
最近落子：{history}

合法落点（必须从中选一个，共 {len(legal_list)} 个）：
{", ".join(legal_list) if legal_list else "（无）"}

按下面三行回复。落子必须是上面列表中的一项，列用大写字母，例如 {example}：
分析：...
策略：...
落子：{example}
"""
        if retry_hint:
            prompt += f"\n上次错误：{retry_hint}\n请改选另一个合法落点，并且用「落子：{example}」这种格式。\n"
        if strict_output:
            prompt += f"\n这是最后一次机会。请只输出一行：\n落子：{example}\n不要输出其他内容，必须替换为合法落点列表中的一个。\n"
        return prompt

    def parse_model_response(self, response: str, legal_moves: List[str] = None) -> Optional[Dict]:
        """只认五子棋落点。象棋四字坐标（如 h7e7）不会被拆成落点。"""
        if not response:
            return None
        text = _normalize_width(response)
        analysis_match = re.search(r"分析\s*[:：]\s*(.+?)(?=策略\s*[:：]|落子\s*[:：]|$)", text, re.DOTALL)
        strategy_match = re.search(r"策略\s*[:：]\s*(.+?)(?=落子\s*[:：]|$)", text, re.DOTALL)
        analysis = analysis_match.group(1).strip() if analysis_match else ""
        strategy = strategy_match.group(1).strip() if strategy_match else ""
        legal_set = set()
        for item in legal_moves or []:
            canon = self.normalize_move(item)
            if canon:
                legal_set.add(canon)

        coord_re = r"([A-O])\s*(1[0-5]|[1-9])(?![A-Za-z0-9])"
        labeled = []
        for match in re.finditer(r"落子\s*[:：]\s*[`*\"“”\[\(（\s]*" + coord_re, text, re.IGNORECASE):
            canon = self.normalize_move(match.group(1) + match.group(2))
            if canon:
                labeled.append(canon)
        standalone = []
        for match in re.finditer(r"(?<![A-Za-z0-9])" + coord_re, text, re.IGNORECASE):
            canon = self.normalize_move(match.group(1) + match.group(2))
            if canon:
                standalone.append(canon)

        move = None
        if legal_set:
            legal_labeled = [item for item in labeled if item in legal_set]
            legal_free = [item for item in standalone if item in legal_set]
            if legal_labeled:
                move = legal_labeled[-1]
            elif legal_free:
                move = legal_free[-1]
        if move is None and labeled:
            move = labeled[-1]
        elif move is None and standalone:
            move = standalone[-1]
        if not move:
            return None
        return {
            "move": move,
            "analysis": analysis,
            "strategy": strategy,
            "thinking": f"分析: {analysis}\n策略: {strategy}".strip(),
            "raw_response": response,
            "in_legal_list": (move in legal_set) if legal_set else None,
        }

    def retry_hint(self, detail: str, example: str) -> str:
        return f"{detail}。请严格按照「落子：{example}」格式回复，且必须是合法落点列表中的一个。"

    def get_last_move(self) -> Optional[dict]:
        return self.move_history[-1] if self.move_history else None
