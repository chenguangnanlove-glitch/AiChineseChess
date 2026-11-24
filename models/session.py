"""把开局请求变成一盘隔离的对局：游戏、模式、双方身份。"""
from __future__ import annotations

from .api_config import ConfigError, player_kwargs, validate_config
from .chess_game import ChessGame
from .gomoku_game import GomokuGame
from .human_player import HumanPlayer
from .llm_player import LLMPlayer

GAMES = ("xiangqi", "gomoku")
MODES = ("ai_vs_ai", "human_vs_ai", "local_pvp")


def is_new_style(data: dict) -> bool:
    return any(key in data for key in ("game", "mode", "human_side"))


def _side_pair(game: str):
    if game == "xiangqi":
        return ("red", "black"), ("红方（先手）", "黑方（后手）")
    if game == "gomoku":
        return ("black", "white"), ("黑棋（先手）", "白棋（后手）")
    raise ConfigError("请选择中国象棋或五子棋")


def _human_name(game: str, side: str) -> str:
    if game == "xiangqi":
        return "玩家（红方）" if side == "red" else "玩家（黑方）"
    return "玩家（黑棋）" if side == "black" else "玩家（白棋）"


def _read_ai_config(data: dict, side: str, label: str) -> dict:
    raw = data.get(f"{side}_player")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"{label}需要填写模型配置（只填这一侧；本机地址可以不填 key）")
    try:
        return validate_config(raw)
    except ConfigError as exc:
        raise ConfigError(f"{label}：{exc}") from exc


def build_spec(data: dict, socketio=None) -> dict:
    """校验开局参数并创建玩家对象。此时还不会替换正在进行的对局，也不会调用模型。"""
    if not isinstance(data, dict):
        raise ConfigError("对局配置必须是 JSON 对象")
    if not is_new_style(data):
        try:
            red = validate_config(data.get("red_player") or {})
        except ConfigError as exc:
            raise ConfigError(f"红方配置：{exc}") from exc
        try:
            black = validate_config(data.get("black_player") or {})
        except ConfigError as exc:
            raise ConfigError(f"黑方配置：{exc}") from exc
        red_player = LLMPlayer(**player_kwargs(red), socketio=socketio)
        black_player = LLMPlayer(**player_kwargs(black), socketio=socketio)
        red_player.kind = "ai"
        black_player.kind = "ai"
        game = ChessGame()
        return {
            "new_style": False,
            "game_type": "xiangqi",
            "mode": "ai_vs_ai",
            "human_side": None,
            "game": game,
            "players": {"red": red_player, "black": black_player},
            "order": ("red", "black"),
            "labels": {"red": "红方", "black": "黑方"},
        }

    game_type = data.get("game") or "xiangqi"
    mode = data.get("mode") or "ai_vs_ai"
    if game_type not in GAMES:
        raise ConfigError("游戏只能选中国象棋（xiangqi）或五子棋（gomoku）")
    if mode not in MODES:
        raise ConfigError("对局方式只能选人机、AI 对 AI 或同机双人")
    order, pretty = _side_pair(game_type)
    first, second = order
    labels = {first: pretty[0].split("（")[0], second: pretty[1].split("（")[0]}
    human_order = data.get("human_side") or "first"
    if mode == "human_vs_ai" and human_order not in ("first", "second"):
        raise ConfigError("人机对战请选择先手或后手")

    players = {}
    if mode == "local_pvp":
        players[first] = HumanPlayer(_human_name(game_type, first))
        players[second] = HumanPlayer(_human_name(game_type, second))
        human_order = None
    elif mode == "human_vs_ai":
        human_side = first if human_order == "first" else second
        ai_side = second if human_side == first else first
        ai_label = pretty[0] if ai_side == first else pretty[1]
        cfg = _read_ai_config(data, ai_side, f"AI {ai_label}")
        ai_player = LLMPlayer(**player_kwargs(cfg), socketio=socketio)
        ai_player.kind = "ai"
        players[human_side] = HumanPlayer(_human_name(game_type, human_side))
        players[ai_side] = ai_player
    else:
        for side, label in zip(order, pretty):
            cfg = _read_ai_config(data, side, label)
            player = LLMPlayer(**player_kwargs(cfg), socketio=socketio)
            player.kind = "ai"
            players[side] = player
        human_order = None

    game = ChessGame() if game_type == "xiangqi" else GomokuGame()
    return {
        "new_style": True,
        "game_type": game_type,
        "mode": mode,
        "human_side": human_order,
        "game": game,
        "players": players,
        "order": order,
        "labels": labels,
    }
