from typing import List, Optional, Dict, Tuple
import time
import copy
import os

class ChessGame:
    """中国象棋游戏核心逻辑类"""
    
    def __init__(self):
        self.board = self.init_board()
        self.move_history = []
        self.current_player = "red"  # red=红方, black=黑方
        self.start_time = time.time()
        self.move_times = []
        # 步数上限（双方合计半回合数），到达后判和。可用环境变量 AICHESS_MAX_MOVES 调整，0 表示不限
        self.max_moves = self._default_max_moves()
        
        # 棋子名称映射
        self.piece_names = {
            'K': '帅', 'A': '仕', 'B': '相', 'N': '马', 'R': '车', 'C': '炮', 'P': '兵',
            'k': '将', 'a': '士', 'b': '象', 'n': '马', 'r': '车', 'c': '炮', 'p': '卒'
        }
        
    @staticmethod
    def _default_max_moves() -> int:
        raw = os.environ.get("AICHESS_MAX_MOVES", "").strip()
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                pass
        return 300

    def init_board(self) -> List[List[str]]:
        """初始化中国象棋棋盘"""
        board = [
            ['r', 'n', 'b', 'a', 'k', 'a', 'b', 'n', 'r'],  # 黑方后排
            ['.', '.', '.', '.', '.', '.', '.', '.', '.'],    # 空行
            ['.', 'c', '.', '.', '.', '.', '.', 'c', '.'],    # 黑炮
            ['p', '.', 'p', '.', 'p', '.', 'p', '.', 'p'],    # 黑兵
            ['.', '.', '.', '.', '.', '.', '.', '.', '.'],    # 楚河汉界
            ['.', '.', '.', '.', '.', '.', '.', '.', '.'],    # 楚河汉界
            ['P', '.', 'P', '.', 'P', '.', 'P', '.', 'P'],    # 红兵
            ['.', 'C', '.', '.', '.', '.', '.', 'C', '.'],    # 红炮
            ['.', '.', '.', '.', '.', '.', '.', '.', '.'],    # 空行
            ['R', 'N', 'B', 'A', 'K', 'A', 'B', 'N', 'R']    # 红方后排
        ]
        return board
    
    def make_move(self, move_str: str) -> bool:
        """执行棋步
        
        Args:
            move_str: 棋步字符串，如 "a0a1" 或中文记谱法如 "炮二平五"
            
        Returns:
            bool: 是否成功执行棋步
        """
        try:
            # 解析棋步
            if len(move_str) == 4 and move_str[0].isalpha():
                # 坐标格式：如 "a0a1"
                from_pos = self.coord_to_pos(move_str[:2])
                to_pos = self.coord_to_pos(move_str[2:])
            else:
                # 中文记谱法：如 "炮二平五"
                from_pos, to_pos = self.parse_chinese_notation(move_str)
                
            if from_pos is None or to_pos is None:
                return False
                
            # 检查是否为合法棋步
            if self.is_valid_move(from_pos, to_pos):
                # 执行移动
                piece = self.board[from_pos[0]][from_pos[1]]
                captured_piece = self.board[to_pos[0]][to_pos[1]]
                
                self.board[to_pos[0]][to_pos[1]] = piece
                self.board[from_pos[0]][from_pos[1]] = '.'
                
                # 记录棋步
                self.move_history.append({
                    'move': move_str,
                    'from_pos': from_pos,
                    'to_pos': to_pos,
                    'piece': piece,
                    'captured': captured_piece,
                    'player': self.current_player,
                    'timestamp': time.time(),
                    'notation': self.pos_to_chinese_notation(from_pos, to_pos, piece)
                })
                
                self.switch_player()
                return True
            else:
                return False
                
        except Exception as e:
            print(f"棋步解析错误: {e}")
            return False
    
    def coord_to_pos(self, coord: str) -> Optional[Tuple[int, int]]:
        """将坐标转换为位置 (行, 列)"""
        if len(coord) != 2:
            return None
        col = ord(coord[0].lower()) - ord('a')  # a-i -> 0-8
        row = int(coord[1])  # 0-9
        if 0 <= col <= 8 and 0 <= row <= 9:
            return (row, col)
        return None
    
    def pos_to_coord(self, pos: Tuple[int, int]) -> str:
        """将位置转换为坐标"""
        row, col = pos
        return chr(ord('a') + col) + str(row)
    
    def parse_chinese_notation(self, notation: str) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
        """解析中文记谱法"""
        # 这里简化处理，实际需要复杂的中文记谱解析
        # 暂时返回None，让系统使用坐标格式
        return None, None
    
    def pos_to_chinese_notation(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int], piece: str) -> str:
        """将移动转换为中文记谱法"""
        piece_name = self.piece_names.get(piece, piece)
        from_col = ['一', '二', '三', '四', '五', '六', '七', '八', '九'][from_pos[1]]
        to_col = ['一', '二', '三', '四', '五', '六', '七', '八', '九'][to_pos[1]]
        
        if from_pos[1] == to_pos[1]:  # 直进直退
            if from_pos[0] > to_pos[0]:
                action = '进'
                steps = from_pos[0] - to_pos[0]
            else:
                action = '退'
                steps = to_pos[0] - from_pos[0]
            return f"{piece_name}{from_col}{action}{['一', '二', '三', '四', '五', '六', '七', '八', '九'][steps-1]}"
        else:  # 平移
            return f"{piece_name}{from_col}平{to_col}"
    
    # ------------------------------------------------------------------
    # 规则核心：伪合法走法（只看棋子走法）+ 将军检测 + 真正合法走法
    # 坐标：board[row][col]，row 0 在上（黑方底线），row 9 在下（红方底线）。
    # 大写=红方，小写=黑方。红方九宫 row 7-9，黑方九宫 row 0-2，col 3-5。
    # ------------------------------------------------------------------

    @staticmethod
    def _color_of(piece: str) -> Optional[str]:
        if not piece or piece == '.':
            return None
        return "red" if piece.isupper() else "black"

    @staticmethod
    def _opponent(color: str) -> str:
        return "black" if color == "red" else "red"

    def _piece_can_reach(self, board: List[List[str]], from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> bool:
        """只按棋子自身走法判断 from→to 是否可达（不判断轮到谁、不判断走后是否被将）。

        to 上若是己方棋子返回 False。棋子颜色由大小写决定，与 current_player 无关，
        所以既能生成己方走法，也能判断对方棋子是否“攻击”某格（将军检测）。
        """
        fr, fc = from_pos
        tr, tc = to_pos
        if not (0 <= tr <= 9 and 0 <= tc <= 8 and 0 <= fr <= 9 and 0 <= fc <= 8):
            return False
        if from_pos == to_pos:
            return False
        piece = board[fr][fc]
        if piece == '.':
            return False
        color = self._color_of(piece)
        target = board[tr][tc]
        if target != '.' and self._color_of(target) == color:
            return False
        kind = piece.lower()
        dr, dc = tr - fr, tc - fc
        adr, adc = abs(dr), abs(dc)

        def in_palace(r, c):
            if not (3 <= c <= 5):
                return False
            return (7 <= r <= 9) if color == "red" else (0 <= r <= 2)

        if kind == 'k':
            return in_palace(tr, tc) and adr + adc == 1
        if kind == 'a':
            return in_palace(tr, tc) and adr == 1 and adc == 1
        if kind == 'b':
            if color == "red" and tr < 5:
                return False
            if color == "black" and tr > 4:
                return False
            if adr == 2 and adc == 2:
                return board[fr + dr // 2][fc + dc // 2] == '.'  # 象眼
            return False
        if kind == 'n':
            if (adr, adc) == (2, 1):
                return board[fr + dr // 2][fc] == '.'  # 蹩马腿
            if (adr, adc) == (1, 2):
                return board[fr][fc + dc // 2] == '.'
            return False
        if kind in ('r', 'c'):
            if dr != 0 and dc != 0:
                return False
            between = self._count_between(board, from_pos, to_pos)
            if kind == 'r':
                return between == 0
            if target == '.':
                return between == 0
            return between == 1  # 炮隔一子吃
        if kind == 'p':
            forward = -1 if color == "red" else 1
            crossed = (fr <= 4) if color == "red" else (fr >= 5)
            if dr == forward and dc == 0:
                return True
            if crossed and dr == 0 and adc == 1:
                return True
            return False
        return False

    @staticmethod
    def _count_between(board, a, b) -> int:
        (ar, ac), (br, bc) = a, b
        count = 0
        if ar == br:
            for c in range(min(ac, bc) + 1, max(ac, bc)):
                if board[ar][c] != '.':
                    count += 1
        else:
            for r in range(min(ar, br) + 1, max(ar, br)):
                if board[r][ac] != '.':
                    count += 1
        return count

    @staticmethod
    def find_king(board, color: str) -> Optional[Tuple[int, int]]:
        target = 'K' if color == "red" else 'k'
        for r in range(10):
            for c in range(9):
                if board[r][c] == target:
                    return (r, c)
        return None

    def kings_facing(self, board=None) -> bool:
        """将帅同列且中间无子（白脸将/对脸）。"""
        board = board if board is not None else self.board
        rk = self.find_king(board, "red")
        bk = self.find_king(board, "black")
        if not rk or not bk or rk[1] != bk[1]:
            return False
        return self._count_between(board, rk, bk) == 0

    def checking_pieces(self, color: str, board=None) -> List[str]:
        """返回正在将 color 方的对方棋子坐标列表（含白脸将时对方的将/帅）。"""
        board = board if board is not None else self.board
        king = self.find_king(board, color)
        if king is None:
            return []
        attackers = []
        for r in range(10):
            for c in range(9):
                p = board[r][c]
                if p == '.' or self._color_of(p) == color:
                    continue
                if p.lower() == 'k':
                    continue  # 将帅互攻只通过白脸将判断
                if self._piece_can_reach(board, (r, c), king):
                    attackers.append(self.pos_to_coord((r, c)))
        if self.kings_facing(board):
            other = self.find_king(board, self._opponent(color))
            attackers.append(self.pos_to_coord(other))
        return attackers

    def is_in_check(self, color: str = None, board=None) -> bool:
        """color 方是否正被将军（含白脸将）。默认检查当前轮到的一方。"""
        color = color or self.current_player
        board = board if board is not None else self.board
        if self.find_king(board, color) is None:
            return True
        return bool(self.checking_pieces(color, board))

    def _pseudo_moves(self, color: str, board=None) -> List[Tuple[Tuple[int, int], Tuple[int, int]]]:
        board = board if board is not None else self.board
        moves = []
        for r in range(10):
            for c in range(9):
                p = board[r][c]
                if p == '.' or self._color_of(p) != color:
                    continue
                for tr, tc in self._candidate_targets(p.lower(), r, c):
                    if self._piece_can_reach(board, (r, c), (tr, tc)):
                        moves.append(((r, c), (tr, tc)))
        return moves

    @staticmethod
    def _candidate_targets(kind: str, r: int, c: int):
        if kind in ('r', 'c'):
            for rr in range(10):
                if rr != r:
                    yield (rr, c)
            for cc in range(9):
                if cc != c:
                    yield (r, cc)
            return
        if kind == 'n':
            offs = [(2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2)]
        elif kind == 'b':
            offs = [(2, 2), (2, -2), (-2, 2), (-2, -2)]
        elif kind == 'a':
            offs = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        else:  # k, p
            offs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        for dr, dc in offs:
            tr, tc = r + dr, c + dc
            if 0 <= tr <= 9 and 0 <= tc <= 8:
                yield (tr, tc)

    def _leaves_king_safe(self, from_pos, to_pos, color: str) -> bool:
        """模拟走子后，color 方不被将军且不白脸。"""
        board = self.board
        piece = board[from_pos[0]][from_pos[1]]
        captured = board[to_pos[0]][to_pos[1]]
        board[to_pos[0]][to_pos[1]] = piece
        board[from_pos[0]][from_pos[1]] = '.'
        try:
            return not self.is_in_check(color, board)
        finally:
            board[from_pos[0]][from_pos[1]] = piece
            board[to_pos[0]][to_pos[1]] = captured

    def is_valid_move(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> bool:
        """完整合法性：当前方棋子、符合走法、走完后己方不被将军、不白脸。"""
        try:
            piece = self.board[from_pos[0]][from_pos[1]]
        except (IndexError, TypeError):
            return False
        if piece == '.' or self._color_of(piece) != self.current_player:
            return False
        if not self._piece_can_reach(self.board, from_pos, to_pos):
            return False
        return self._leaves_king_safe(from_pos, to_pos, self.current_player)

    def is_pseudo_legal_move(self, from_pos, to_pos) -> bool:
        """只看棋子走法（旧版 is_valid_move 的语义），供调试/测试对比。"""
        piece = self.board[from_pos[0]][from_pos[1]]
        if piece == '.' or self._color_of(piece) != self.current_player:
            return False
        return self._piece_can_reach(self.board, from_pos, to_pos)

    def check_piece_move_rules(self, piece_type: str, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> bool:
        """兼容旧接口：只按棋子走法判断。"""
        return self._piece_can_reach(self.board, from_pos, to_pos)

    def switch_player(self):
        """切换当前玩家"""
        self.current_player = "black" if self.current_player == "red" else "red"

    def get_board_state(self) -> str:
        """获取当前棋盘状态（自定义格式：10 行用 / 分隔）"""
        return "/".join("".join(row) for row in self.board)

    def load_board_state(self, board_state: str, current_player: str = "red"):
        """从 get_board_state() 的格式恢复局面（测试/复盘用）。"""
        rows = board_state.strip().split("/")
        if len(rows) != 10 or any(len(r) != 9 for r in rows):
            raise ValueError("棋盘格式应为 10 行、每行 9 格，用 / 分隔")
        self.board = [list(r) for r in rows]
        self.current_player = current_player
        self.move_history = []

    def get_board_unicode(self) -> str:
        """获取棋盘的Unicode字符串表示"""
        result = "  a b c d e f g h i\n"
        for i, row in enumerate(self.board):
            result += f"{i} "
            for piece in row:
                result += "· " if piece == '.' else f"{self.piece_names.get(piece, piece)} "
            result += f"{i}\n"
        result += "  a b c d e f g h i"
        return result

    def get_legal_moves(self) -> List[str]:
        """当前方的全部合法棋步：伪合法走法中，走完后己方不被将军且不白脸的。"""
        color = self.current_player
        moves = []
        for from_pos, to_pos in self._pseudo_moves(color):
            if self._leaves_king_safe(from_pos, to_pos, color):
                moves.append(self.pos_to_coord(from_pos) + self.pos_to_coord(to_pos))
        return moves

    def get_game_status(self) -> Dict:
        """判断对局是否结束。

        返回 {"over": bool, "winner": "red"/"black"/None, "reason": 代码, "message": 中文说明}
        reason: checkmate 将死 / stalemate 困毙 / king_captured 将帅被吃（旧局面兼容）/
                move_limit 步数上限判和 / ongoing
        """
        red_k = self.find_king(self.board, "red")
        black_k = self.find_king(self.board, "black")
        side = "红方" if self.current_player == "red" else "黑方"
        if not red_k or not black_k:
            winner = "red" if red_k else ("black" if black_k else None)
            return {"over": True, "winner": winner, "reason": "king_captured",
                    "message": f"{'红方' if winner == 'red' else '黑方'}吃掉对方将帅获胜" if winner else "双方将帅均不在棋盘上"}
        if not self.get_legal_moves():
            winner = self._opponent(self.current_player)
            wname = "红方" if winner == "red" else "黑方"
            if self.is_in_check(self.current_player):
                return {"over": True, "winner": winner, "reason": "checkmate",
                        "message": f"{side}被将死，{wname}获胜"}
            return {"over": True, "winner": winner, "reason": "stalemate",
                    "message": f"{side}无子可动（困毙），{wname}获胜"}
        if self.max_moves and len(self.move_history) >= self.max_moves:
            return {"over": True, "winner": None, "reason": "move_limit",
                    "message": f"双方已走满 {self.max_moves} 步（{self.max_moves // 2} 回合）仍未分胜负，判和"}
        return {"over": False, "winner": None, "reason": "ongoing", "message": "对局进行中"}

    def is_game_over(self) -> bool:
        """判断游戏是否结束（将死、困毙、将帅被吃、步数上限）"""
        return self.get_game_status()["over"]

    def get_game_result(self) -> str:
        """获取游戏结果（中文）"""
        status = self.get_game_status()
        if not status["over"]:
            return "游戏进行中"
        if status["winner"] == "red":
            return "红方获胜"
        if status["winner"] == "black":
            return "黑方获胜"
        return "平局"

    def get_pgn(self) -> str:
        """简单棋谱：坐标走法，空格分隔。"""
        return " ".join(m.get('move', '') for m in self.move_history)


    def get_move_count(self) -> int:
        """获取总步数"""
        return len(self.move_history)
    
    def get_last_move(self) -> Optional[Dict]:
        """获取最后一步棋"""
        if self.move_history:
            return self.move_history[-1]
        return None
    
    def reset(self):
        """重置游戏"""
        self.board = self.init_board()
        self.move_history = []
        self.current_player = "red"
        self.start_time = time.time()
        self.move_times = []
    
    def get_position_evaluation(self) -> float:
        """简单的局面评估（基于材料价值）"""
        piece_values = {
            'k': 1000, 'a': 20, 'b': 20, 'n': 40, 'r': 90, 'c': 45, 'p': 10,
            'K': 1000, 'A': 20, 'B': 20, 'N': 40, 'R': 90, 'C': 45, 'P': 10
        }
        
        red_value = 0
        black_value = 0
        
        for row in self.board:
            for piece in row:
                if piece != '.':
                    value = piece_values.get(piece, 0)
                    if piece.isupper():
                        red_value += value
                    else:
                        black_value += value
        
        return (red_value - black_value) / 100.0  # 归一化
    
    def undo_last_move(self) -> bool:
        """撤销最后一步棋"""
        if not self.move_history:
            return False
            
        last_move = self.move_history.pop()
        from_pos = last_move['from_pos']
        to_pos = last_move['to_pos']
        piece = last_move['piece']
        captured = last_move['captured']
        
        # 恢复棋盘状态
        self.board[from_pos[0]][from_pos[1]] = piece
        self.board[to_pos[0]][to_pos[1]] = captured
        
        self.switch_player()
        return True