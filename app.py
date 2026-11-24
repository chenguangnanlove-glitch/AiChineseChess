from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import os
import time
import threading
import traceback
import requests
import json
from models.api_config import validate_config, build_payload, ConfigError, run_compat_request, parse_chat_completion_json, parse_anthropic_message
from models.battle import ChessBattle
from models.game_recorder import GameRecorder
from models.session import build_spec
from models.network_errors import (
    network_backoff_schedule,
    is_network_error,
    friendly_network_message,
)
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
# 线程模式：Python 3.12 下 eventlet 0.33.3 无法导入，显式指定，避免不同机器上行为不一致。
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
GAMES_DIR = os.path.join(APP_ROOT, "games")

# 全局变量存储当前对战。每盘棋有自己的对战线程（battle.loop_thread），
# 旧线程发现自己不再是 current_battle 就自行退出，不会挡住新开局。
current_battle = None
state_lock = threading.RLock()
_battle_seq = 0

MAX_ILLEGAL_ATTEMPTS = 3


def _env_float(name, default):
    raw = os.environ.get(name, "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return default


def move_delay_seconds():
    return _env_float("AICHESS_MOVE_DELAY", 1.0)


def step_timeout_seconds():
    """单次模型调用的总时长上限（含思考与流式输出）。超时按网络问题处理并重试。"""
    return _env_float("AICHESS_STEP_TIMEOUT", 420.0)


@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')


def _recorder(battle):
    return getattr(battle, "recorder", None) if battle else None


# ----------------------------------------------------------------------
# 状态快照：页面刷新 / socket 重连 / 定时轮询都用它恢复界面
# ----------------------------------------------------------------------

def new_battle_id() -> str:
    global _battle_seq
    _battle_seq += 1
    return f"{int(time.time() * 1000)}-{_battle_seq}"


def player_of(battle, color):
    if battle is None:
        return None
    if hasattr(battle, "player_for"):
        return battle.player_for(color)
    if color == "red":
        return battle.red_player
    return battle.black_player


def public_player(player):
    if player is None:
        return None
    return {
        "display_name": getattr(player, "display_name", ""),
        "model_name": getattr(player, "model_name", ""),
        "kind": getattr(player, "kind", "ai"),
    }


def check_context(game, color):
    """只有中国象棋有将军。五子棋不要套用这套判断。"""
    if getattr(game, "game_type", "xiangqi") != "xiangqi":
        return False, []
    try:
        in_check = bool(game.is_in_check(color))
    except Exception:
        return False, []
    checkers = []
    if in_check:
        try:
            checkers = game.checking_pieces(color)
        except Exception:
            checkers = []
    return in_check, checkers


def turn_still_current(battle, battle_id) -> bool:
    return (
        battle is not None
        and battle is current_battle
        and getattr(battle, "battle_id", None) == battle_id
        and getattr(battle, "status", "") == "playing"
    )


def emit_battle(battle, event, payload):
    """只向当前这一盘推送。旧对局的迟到结果不能进新棋盘。"""
    if battle is None or battle is not current_battle:
        return
    if not isinstance(payload, dict):
        payload = {"message": str(payload)}
    body = dict(payload)
    body.setdefault("battle_id", getattr(battle, "battle_id", None))
    body.setdefault("game", getattr(battle, "game_type", "xiangqi"))
    try:
        socketio.emit(event, body)
    except Exception as e:
        print(f"推送 {event} 失败（不影响对局）: {e}")


def explain_illegal(game, raw: str) -> str:
    if game.is_game_over():
        return "对局已经结束，不能再走"
    if getattr(game, "game_type", "") == "gomoku":
        canon = game.normalize_move(raw)
        if not canon:
            return "落点无效。五子棋请点空的交叉点（列 A–O，行 1–15，例如 H8），不能用象棋的四字坐标"
        pos = game.coord_to_pos(canon)
        if pos and game.board[pos[0]][pos[1]] != ".":
            return "这个交叉点已经有棋子了"
        return "这个位置现在不能下"
    return "这一步不合法。请先点自己的棋子，再点能走到的位置（不能吃自己的子，被将军时必须应将）"


def loop_alive(battle) -> bool:
    t = getattr(battle, "loop_thread", None) if battle else None
    return bool(t is not None and t.is_alive())


def battle_snapshot(battle):
    if battle is None:
        return {"status": "no_battle", "phase": "idle", "can_resume": False, "can_retry_now": False}
    game = battle.game
    alive = loop_alive(battle)
    status = getattr(battle, "status", "playing")
    phase = getattr(battle, "phase", "idle")
    stalled = status == "playing" and not alive
    if stalled:
        phase = "stalled"
    recorder = _recorder(battle)
    color = game.current_player
    in_check, _checkers = check_context(game, color)
    result = getattr(battle, "result", None)
    finished = status == "finished"
    game_type = getattr(battle, "game_type", getattr(game, "game_type", "xiangqi"))
    mode = getattr(battle, "mode", "ai_vs_ai")
    players = {}
    labels = {}
    human_sides = []
    order = getattr(battle, "side_order", None) or tuple(getattr(battle, "players", {"red": None, "black": None}))
    for side in order:
        person = player_of(battle, side)
        if person is None:
            continue
        players[side] = public_player(person)
        labels[side] = game.side_label(side) if hasattr(game, "side_label") else side
        if getattr(person, "kind", "ai") == "human":
            human_sides.append(side)
    your_turn = (not finished) and status == "playing" and phase == "human_turn" and color in human_sides
    match_bits = []
    for side, person in players.items():
        who = person["display_name"]
        match_bits.append(f"{labels.get(side, side)}：{who}")
    snapshot = {
        "battle_id": getattr(battle, "battle_id", None),
        "seq": getattr(battle, "state_seq", 0),
        "status": status,
        "phase": phase,
        "phase_message": getattr(battle, "phase_message", "") or "",
        "phase_since": getattr(battle, "phase_since", None),
        "server_time": time.time(),
        "loop_alive": alive,
        "stalled": stalled,
        "can_resume": (not finished) and status != "stopped" and (status == "paused" or stalled),
        "can_retry_now": (not finished) and status == "playing" and alive and phase in ("network_retry", "thinking"),
        "pause_reason": getattr(battle, "pause_reason", None),
        "board_state": game.get_board_state(),
        "move_count": len(game.move_history),
        "current_player": color,
        "in_check": in_check,
        "is_game_over": finished,
        "result": result,
        "game": game_type,
        "mode": mode,
        "rules": game.rules_summary() if hasattr(game, "rules_summary") else "",
        "side_labels": labels,
        "players": players,
        "human_sides": human_sides,
        "your_turn": your_turn,
        "legal_moves": game.get_legal_moves() if your_turn else [],
        "match_label": " · ".join(match_bits),
        "moves": [
            {"n": i + 1, "player": m.get("player"), "move": m.get("move"),
             "player_name": getattr(player_of(battle, m.get("player")), "display_name", "")}
            for i, m in enumerate(game.move_history)
        ],
        "last_move": game.move_history[-1]["move"] if game.move_history else None,
        "record_path": recorder.path if recorder else None,
    }
    if game_type == "xiangqi":
        snapshot["red_player"] = players.get("red") or public_player(getattr(battle, "red_player", None))
        snapshot["black_player"] = players.get("black") or public_player(getattr(battle, "black_player", None))
    return snapshot


def emit_state(battle):
    emit_battle(battle, "battle_state", battle_snapshot(battle) if battle is not None else {"status": "no_battle"})


def set_phase(battle, phase, message=""):
    battle.state_seq = getattr(battle, "state_seq", 0) + 1
    battle.phase = phase
    battle.phase_message = message
    battle.phase_since = time.time()
    emit_state(battle)


def is_active(battle) -> bool:
    return battle is not None and battle is current_battle and getattr(battle, "status", "") == "playing"


def wait_or_wake(battle, seconds) -> str:
    """分段等待。返回 'done'（等完）/'wake'（用户点了立即重试）/'stop'（停止、重置、暂停）。"""
    end = time.time() + max(0.0, float(seconds))
    while True:
        if not is_active(battle):
            return "stop"
        if battle.wake_event.is_set():
            battle.wake_event.clear()
            return "wake"
        remaining = end - time.time()
        if remaining <= 0:
            return "done"
        battle.wake_event.wait(min(0.2, remaining))


def cancel_inflight(battle):
    players = battle.iter_players() if hasattr(battle, "iter_players") else (
        getattr(battle, "red_player", None), getattr(battle, "black_player", None)
    )
    for player in players:
        if player is not None:
            try:
                player.cancel_call()
            except Exception:
                pass


def pause_battle(battle, message, kind="network"):
    """暂停在当前局面（不结束对局），页面显示「继续对战」。"""
    if battle is None or battle is not current_battle or getattr(battle, "status", "") in ("finished", "stopped"):
        return
    battle.status = "paused"
    battle.pause_reason = message
    battle.pause_kind = kind
    recorder = _recorder(battle)
    if recorder:
        try:
            recorder.set_status("paused", reason=message)
        except Exception as e:
            print(f"写入棋谱状态失败: {e}")
    print(f"对局已暂停（不结束），可点「继续对战」。原因: {message}")
    player = player_of(battle, battle.game.current_player)
    emit_battle(battle, "battle_paused", {
        "message": message,
        "kind": kind,
        "player": player.display_name,
        "current_player": battle.game.current_player,
        "board_state": battle.game.get_board_state(),
        "move_count": len(battle.game.move_history),
        "record_path": recorder.path if recorder else None,
        "can_resume": True,
    })
    set_phase(battle, "paused", message)


def finish_battle(battle):
    battle.status = "finished"
    result = battle.get_battle_result()
    battle.result = result
    recorder = _recorder(battle)
    if recorder:
        try:
            recorder.data["end_reason"] = result.get("reason")
            recorder.data["end_message"] = result.get("message")
            recorder.set_status("finished", result=result)
        except Exception as e:
            print(f"写入棋谱结果失败: {e}")
    print(f"游戏结束: {result.get('message')}")
    emit_battle(battle, "game_over", {
        "result": result,
        "message": result.get("message"),
        "winner_color": result.get("winner_color"),
        "reason": result.get("reason"),
        "total_moves": len(battle.game.move_history),
        "board_state": battle.game.get_board_state(),
        "record_path": recorder.path if recorder else None,
    })
    set_phase(battle, "finished", result.get("message", ""))


# ----------------------------------------------------------------------
# 模型调用：放在工作线程里，对战线程只负责等待，所以停止/重置/立即重试随时生效
# ----------------------------------------------------------------------

def call_model(battle, player, **kwargs):
    """返回 (outcome, value)。outcome: ok / stop / wake / timeout / exception"""
    battle_id = getattr(battle, "battle_id", None)
    token = object()
    box = {}
    done = threading.Event()

    def work():
        try:
            player.begin_call(token)
            box["result"] = player.get_move(**kwargs)
        except BaseException as e:  # noqa
            box["exc"] = e
        finally:
            done.set()

    worker = threading.Thread(target=work, name="llm-call", daemon=True)
    worker.start()
    deadline = time.time() + (step_timeout_seconds() if os.environ.get("AICHESS_STEP_TIMEOUT") else max(step_timeout_seconds(), getattr(player, "timeout", 0)))
    while not done.wait(0.2):
        battle.heartbeat = time.time()
        if not turn_still_current(battle, battle_id):
            player.cancel_call(token)
            return "stop", None
        if battle.wake_event.is_set():
            battle.wake_event.clear()
            player.cancel_call(token)
            return "wake", None
        if time.time() > deadline:
            player.cancel_call(token)
            return "timeout", None
    if not turn_still_current(battle, battle_id):
        return "stop", None
    if "exc" in box:
        return "exception", box["exc"]
    result = box.get("result")
    if isinstance(result, dict) and result.get("error_type") == "cancelled":
        return "stop", None
    return "ok", result


def _is_network_result(move_result) -> bool:
    if not isinstance(move_result, dict):
        return False
    if move_result.get("error_type") == "network":
        return True
    text = " ".join(str(move_result.get(k) or "") for k in ("error", "detail"))
    return bool(text.strip()) and is_network_error(error_text=text)


def _hint(game, detail: str, example: str = "") -> str:
    if hasattr(game, "retry_hint"):
        return game.retry_hint(detail, example)
    return f"{detail}。请严格按照「棋步：xxxx」格式回复，且必须是合法列表中的一步。"


def _canonical_move(game, raw: str) -> str:
    if getattr(game, "game_type", "xiangqi") == "gomoku" and hasattr(game, "normalize_move"):
        return game.normalize_move(raw) or str(raw or "").strip().upper()
    return str(raw or "").strip().lower()


def play_human_turn(battle, color, player) -> str:
    """等人在棋盘上走。不调用模型。"""
    battle_id = battle.battle_id
    game = battle.game
    label = game.side_label(color) if hasattr(game, "side_label") else color
    msg = f"轮到{player.display_name}（{label}），请在棋盘上走棋"
    battle.awaiting = "human"
    battle.pending_human_move = None
    battle.human_event.clear()
    emit_battle(battle, "your_turn", {
        "player": color,
        "message": msg,
        "legal_moves": game.get_legal_moves(),
    })
    set_phase(battle, "human_turn", msg)
    while turn_still_current(battle, battle_id):
        battle.heartbeat = time.time()
        battle.human_event.wait(0.2)
        with state_lock:
            if not turn_still_current(battle, battle_id):
                battle.pending_human_move = None
                return "stop"
            move = battle.pending_human_move
            if not move:
                battle.human_event.clear()
                continue
            battle.pending_human_move = None
            legal_now = set(game.get_legal_moves())
            if move not in legal_now or not game.make_move(move):
                battle.phase = "human_turn"
                battle.awaiting = "human"
                emit_battle(battle, "move_rejected", {"message": explain_illegal(game, move), "move": move})
                continue
            battle.awaiting = None
        record_move(battle, player, color, move, {"move": move, "thinking": "", "analysis": "", "strategy": ""})
        return "moved"
    battle.pending_human_move = None
    return "stop"


def play_one_turn(battle) -> str:
    """让当前一方走一步。返回 moved / stop / paused。"""
    game = battle.game
    color = game.current_player
    player = player_of(battle, color)
    if getattr(player, "kind", "ai") == "human":
        return play_human_turn(battle, color, player)
    battle.awaiting = "ai"
    battle_id = battle.battle_id
    legal_moves = game.get_legal_moves()
    in_check, checkers = check_context(game, color)
    side = game.side_label(color) if hasattr(game, "side_label") else color
    noun = "落点" if getattr(game, "game_type", "") == "gomoku" else "棋步"
    print(f"当前玩家: {player.display_name} ({color})，合法{noun} {len(legal_moves)} 个" + ("，正被将军" if in_check else ""))

    illegal_attempts = 0
    network_failures = 0
    backoff = network_backoff_schedule()
    retry_hint = None
    last_detail = None

    while turn_still_current(battle, battle_id):
        thinking_msg = f"{player.display_name} 正在思考中..." + ("（正被将军，必须应将）" if in_check else "")
        # 人机对局不在思考过程中推送模型原文，避免提前泄露。
        emit_battle(battle, "thinking", {
            "player": color,
            "message": thinking_msg,
            "reveal": getattr(battle, "mode", "ai_vs_ai") != "human_vs_ai",
        })
        set_phase(battle, "thinking", thinking_msg)

        outcome, value = call_model(
            battle, player,
            board_state=game.get_board_state(),
            move_history=list(game.move_history),
            legal_moves=list(legal_moves),
            retry_hint=retry_hint,
            strict_output=(illegal_attempts > 0),
            in_check=in_check,
            checkers=checkers,
            player_color=color,
            rules=game if hasattr(game, "build_prompt") else None,
            stream_thinking=getattr(battle, "mode", "ai_vs_ai") != "human_vs_ai",
        )
        if outcome == "stop":
            return "stop"
        if outcome == "wake":
            print("用户点击「立即重试」，重新请求当前一方")
            network_failures = 0
            continue

        network_detail = None
        if outcome == "timeout":
            network_detail = f"{player.display_name} 超过 {int(step_timeout_seconds())} 秒没有给出回复"
        elif outcome == "exception":
            if is_network_error(exc=value, error_text=str(value)):
                network_detail = friendly_network_message(player.base_url, str(value))
            else:
                illegal_attempts += 1
                last_detail = f"调用出错：{value}"
                retry_hint = _hint(game, f"{last_detail}。请重新选择一个合法{noun}", legal_moves[0] if legal_moves else "")
                print(f"无效棋步第 {illegal_attempts}/{MAX_ILLEGAL_ATTEMPTS} 次：{value}")
        elif _is_network_result(value):
            network_detail = value.get("error") or friendly_network_message(player.base_url, value.get("detail") or "")
            if "请严格按照" in network_detail:
                network_detail = friendly_network_message(player.base_url, value.get("detail") or "")

        if network_detail:
            if network_failures >= len(backoff):
                pause_battle(battle, f"{network_detail}。已自动重试 {network_failures} 次仍失败，网络恢复后点「继续对战」接着下。", kind="network")
                return "paused"
            delay = backoff[network_failures]
            if isinstance(value, dict) and value.get("retry_after") is not None:
                delay = value["retry_after"]
            network_failures += 1
            msg = f"网络问题，第{network_failures}次重连（{delay:g} 秒后自动重试，也可点「立即重试」）"
            print(f"网络问题（不计入无效棋步）: {network_detail}；{msg}")
            emit_battle(battle, "network_retry", {
                "message": msg,
                "attempt": network_failures,
                "max_attempts": len(backoff),
                "delay": delay,
                "detail": network_detail,
                "player": player.display_name,
                "can_retry_now": True,
            })
            set_phase(battle, "network_retry", f"{msg}：{network_detail}")
            w = wait_or_wake(battle, delay)
            if w == "stop":
                return "stop"
            continue

        if outcome == "ok":
            move_result = value
            if not move_result or not move_result.get("move"):
                detail = (move_result or {}).get("error") or "模型没有返回有效棋步"
                if move_result and move_result.get("fatal"):
                    pause_battle(battle, f"{player.display_name} 接口报错：{detail}。网络/余额恢复后可继续；更换 key 或模型配置请先停止，再重新开局。", kind="api")
                    return "paused"
                illegal_attempts += 1
                last_detail = detail
                retry_hint = _hint(game, detail, legal_moves[0] if legal_moves else "")
                print(f"无效棋步第 {illegal_attempts}/{MAX_ILLEGAL_ATTEMPTS} 次：{detail}")
            else:
                move = _canonical_move(game, move_result["move"])
                applied = False
                with state_lock:
                    if not turn_still_current(battle, battle_id):
                        return "stop"
                    if move in legal_moves and game.make_move(move):
                        applied = True
                if not applied:
                    if not turn_still_current(battle, battle_id):
                        return "stop"
                    illegal_attempts += 1
                    last_detail = f"{noun} {move} 不合法" + ("（你正被将军，必须应将）" if in_check else "")
                    retry_hint = _hint(game, last_detail, legal_moves[0] if legal_moves else "")
                    print(f"无效棋步第 {illegal_attempts}/{MAX_ILLEGAL_ATTEMPTS} 次：{last_detail}")
                else:
                    record_move(battle, player, color, move, move_result)
                    return "moved"

        if illegal_attempts >= MAX_ILLEGAL_ATTEMPTS:
            pause_battle(
                battle,
                f"{player.display_name}（{side}）连续 {MAX_ILLEGAL_ATTEMPTS} 次没有给出合法棋步（{last_detail}）。点「继续对战」让它再试。",
                kind="illegal",
            )
            return "paused"
    return "stop"


def record_move(battle, player, color, move, move_result):
    game = battle.game
    gives_check = False
    if getattr(game, "game_type", "xiangqi") == "xiangqi":
        try:
            gives_check = bool(game.is_in_check(game.current_player))
        except Exception:
            gives_check = False
    noun = "落子" if getattr(game, "game_type", "") == "gomoku" else "棋步"
    print(f"{noun}有效: {move}" + ("，将军！" if gives_check else ""))
    try:
        battle.log_move(player.display_name, move_result)
    except Exception as e:
        print(f"写入对战日志失败（不影响继续下棋）: {e}")
    recorder = _recorder(battle)
    if recorder:
        try:
            recorder.add_move(
                player_color=color,
                player_name=player.display_name,
                model_name=player.model_name,
                move=move,
                thinking=move_result.get("thinking") or "",
                analysis=move_result.get("analysis") or "",
                strategy=move_result.get("strategy") or "",
                board_state=game.get_board_state(),
                thinking_time=move_result.get("thinking_time"),
                notation=game.move_history[-1].get("notation", ""),
                gives_check=gives_check,
            )
        except Exception as e:
            print(f"写入棋谱失败（不影响继续下棋）: {e}")
    # 人机时思考内容只在这一步已经落到棋盘上之后才发给页面，并且默认折叠。
    hide_thinking = getattr(battle, "mode", "") == "human_vs_ai" and getattr(player, "kind", "ai") == "ai"
    thinking = move_result.get("thinking", "") or ""
    analysis = move_result.get("analysis", "") or ""
    strategy = move_result.get("strategy", "") or ""
    emit_battle(battle, "move_made", {
        "player": player.display_name,
        "player_color": color,
        "move": move,
        "thinking": "" if hide_thinking else thinking,
        "analysis": "" if hide_thinking else analysis,
        "strategy": "" if hide_thinking else strategy,
        "thinking_hidden": hide_thinking,
        "sealed_thinking": thinking if hide_thinking else "",
        "sealed_analysis": analysis if hide_thinking else "",
        "sealed_strategy": strategy if hide_thinking else "",
        "board_state": game.get_board_state(),
        "current_player": game.current_player,
        "move_count": len(game.move_history),
        "gives_check": gives_check,
        "action_text": "落子" if getattr(game, "game_type", "") == "gomoku" else "走了",
    })


def run_battle(battle):
    """单盘对战线程。任何异常都会转成「暂停 + 继续对战」，不会静默死掉。"""
    try:
        if battle is None:
            return
        print(f"对战线程启动（已走 {len(battle.game.move_history)} 步，轮到 {battle.game.current_player}）")
        recorder = _recorder(battle)
        if recorder and recorder.data.get("status") != "playing":
            recorder.set_status("playing")
        while is_active(battle):
            battle.heartbeat = time.time()
            if battle.game.is_game_over():
                finish_battle(battle)
                return
            outcome = play_one_turn(battle)
            if outcome != "moved":
                return
            if battle.game.is_game_over():
                finish_battle(battle)
                return
            set_phase(battle, "between_moves", "")
            nxt = player_of(battle, battle.game.current_player)
            delay = 0.05 if getattr(nxt, "kind", "ai") == "human" else move_delay_seconds()
            if wait_or_wake(battle, delay) == "stop":
                return
    except Exception as e:
        print(f"对战线程出现异常: {e}")
        traceback.print_exc()
        if is_active(battle):
            pause_battle(battle, f"程序内部出错：{e}。可点「继续对战」从当前局面接着下。", kind="error")
    finally:
        if battle is not None and is_active(battle):
            # 正常情况下走不到这里；兜底：线程退出但状态仍是 playing，改成可继续
            pause_battle(battle, "对战线程意外停止，可点「继续对战」接着下。", kind="error")
        print("对战线程退出")


def arm_players(battle):
    """迟到的流式输出只允许属于这一盘、并且对局仍在进行。"""
    battle_id = battle.battle_id

    def allowed(expected=battle_id):
        current = current_battle
        return (
            current is not None
            and getattr(current, "battle_id", None) == expected
            and getattr(current, "status", "") == "playing"
        )

    for player in battle.iter_players():
        if player is None:
            continue
        player.battle_id = battle_id
        if getattr(player, "kind", "ai") == "ai":
            player.emit_allowed = allowed


def start_loop(battle) -> bool:
    with battle.loop_lock:
        if loop_alive(battle):
            return False
        battle.loop_thread = socketio.start_background_task(run_battle, battle)
        return True


def _stop_current(reason="stopped"):
    global current_battle
    battle = current_battle
    if battle is None:
        return None
    if battle.status not in ("finished",):
        battle.status = "stopped"
    battle.wake_event.set()
    human_event = getattr(battle, "human_event", None)
    if human_event is not None:
        human_event.set()
    battle.pending_human_move = None
    cancel_inflight(battle)
    recorder = _recorder(battle)
    if recorder and recorder.data.get("status") not in ("finished",):
        try:
            recorder.set_status("stopped", reason=reason if reason != "stopped" else None)
        except Exception as e:
            print(f"写入棋谱状态失败: {e}")
    return battle


def install_battle(spec, data):
    """在已持有 state_lock 时，停掉旧对局并装上全新局面。"""
    global current_battle
    _stop_current()
    players = spec["players"]
    order = spec["order"]
    if spec["game_type"] == "xiangqi":
        first_player, second_player = players["red"], players["black"]
    else:
        first_player, second_player = players[order[0]], players[order[1]]
    battle = ChessBattle(
        first_player, second_player,
        game=spec["game"], mode=spec["mode"], players=players, game_type=spec["game_type"],
    )
    battle.side_order = order
    battle.side_labels = spec["labels"]
    battle.human_side = spec["human_side"]
    battle.awaiting = None
    battle.pending_human_move = None
    battle.human_event = threading.Event()
    battle.status = "playing"
    battle.battle_id = new_battle_id()
    battle.state_seq = 0
    battle.pause_reason = None
    battle.phase = "starting"
    battle.phase_message = ""
    battle.phase_since = time.time()
    battle.result = None
    battle.wake_event = threading.Event()
    battle.loop_lock = threading.Lock()
    battle.loop_thread = None
    battle.heartbeat = time.time()
    rules = battle.game.rules_summary() if hasattr(battle.game, "rules_summary") else ""
    battle.recorder = GameRecorder(
        first_player, second_player, GAMES_DIR,
        game=spec["game_type"], mode=spec["mode"], players=players,
        order=order, rules=rules, labels=spec["labels"],
    )
    if data.get("initial_board"):
        battle.recorder.data["initial_board"] = data["initial_board"]
        battle.recorder.data["initial_player"] = battle.game.current_player
        battle.recorder.save()
    arm_players(battle)
    current_battle = battle
    print(f"对局记录: {battle.recorder.path}")
    start_loop(battle)
    return battle


@app.route('/api/start_battle', methods=['POST'])
def start_battle():
    """开始对战。

    不带 game/mode 时仍是原来的中国象棋 AI 对 AI。
    新界面会带上游戏、模式；若上一盘还在进行，必须 confirm_replace 才会停掉并换新局。
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(status='error', error_type='config', message='对局配置必须是 JSON 对象'), 400
    try:
        spec = build_spec(data, socketio)
        if data.get("initial_board"):
            spec["game"].load_board_state(
                data["initial_board"],
                data.get("initial_player") or spec["order"][0],
            )
    except ConfigError as e:
        return jsonify({"status": "error", "error_type": "config", "message": str(e)}), 400
    except ValueError as e:
        return jsonify({"status": "error", "error_type": "config", "message": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 400
    with state_lock:
        active = current_battle is not None and current_battle.status in ("playing", "paused")
        if spec["new_style"] and active and data.get("confirm_replace") is not True:
            return jsonify({
                "status": "error",
                "error_type": "confirm_required",
                "message": "当前还有一盘未结束的对局。开始新局会停止它并清空棋盘，上一盘的棋子和思考都不会带进新局。确定要新开一局吗？",
            }), 409
        try:
            battle = install_battle(spec, data)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({
        "status": "success",
        "message": "对战已开始",
        "record_path": battle.recorder.path,
        "state": battle_snapshot(battle),
    })


@app.route('/api/human_move', methods=['POST'])
def human_move():
    """人机或同机双人的落子。服务端核对是不是这一盘、是不是你的回合、这一步是否合法。"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(status="error", error_type="illegal", message="走法格式不对"), 400
    with state_lock:
        battle = current_battle
        if battle is None or battle.status in ("stopped", "finished"):
            return jsonify(status="error", error_type="stale", message="没有正在进行的对局，这一步已丢弃"), 409
        if data.get("battle_id") != battle.battle_id:
            return jsonify(status="error", error_type="stale", message="这步棋属于已经停止、重置或换掉的旧对局，不会进入当前棋盘"), 409
        phase = getattr(battle, "phase", "")
        actor = player_of(battle, battle.game.current_player)
        if phase != "human_turn" or getattr(actor, "kind", "ai") != "human":
            if phase in ("thinking", "network_retry", "between_moves", "applying", "starting"):
                return jsonify(status="error", error_type="turn", message="现在不能走棋：请等当前这一步结束。AI 思考时不能替它落子"), 409
            return jsonify(status="error", error_type="turn", message="现在不是你走棋的回合"), 409
        if battle.pending_human_move:
            return jsonify(status="error", error_type="turn", message="上一步还在提交，请稍候"), 409
        raw = str(data.get("move") or "").strip()
        move = _canonical_move(battle.game, raw)
        legal = set(battle.game.get_legal_moves())
        if not move or move not in legal:
            return jsonify(status="error", error_type="illegal", message=explain_illegal(battle.game, raw or move)), 400
        battle.pending_human_move = move
        battle.phase = "applying"
        battle.human_event.set()
    return jsonify(status="success", message="已提交", move=move)


@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    """仅用户点击并确认后调用。一次小额请求；不保存 key/响应正文。

    支持 OpenAI Chat Completions 与 Anthropic Messages。不跟随重定向，保留 TLS 校验。
    自动兼容 max_completion_tokens；本机空 key 不发送鉴权头。
    """
    raw = request.get_json(silent=True) or {}
    if not isinstance(raw, dict) or raw.get('confirmed') is not True:
        return jsonify(status='error', message='请先确认：测试会发送一次小请求，可能产生 API 费用'), 400
    try:
        cfg = validate_config(raw.get('config') or {})
    except ConfigError as e:
        return jsonify(status='error', error_type='config', message=str(e)), 400
    body = build_payload(cfg, [{'role': 'user', 'content': 'Reply OK.'}], stream=False, testing=True)
    timeout = min(cfg['timeout'], 20)
    result_box = {}
    done = threading.Event()

    def probe():
        try:
            resp, payload, status = run_compat_request(
                cfg, body, timeout, connect_timeout=min(10, timeout), allow_redirects=False,
            )
            if status == 'cancelled':
                result_box.update(status='error', http_status=None, message='连接测试已取消')
                return
            code = getattr(resp, 'status_code', None)
            if status != 'ok':
                reason = {400: '模型或参数不支持，请核对 model 和 provider', 401: '认证失败，请检查 key',
                          402: '余额不足或需要开通付费', 403: '没有访问权限或所在地区不可用',
                          404: '接口地址或模型不存在', 422: '模型或参数不支持，请核对 model 和 provider',
                          429: '请求受限或额度不足'}.get(code, '接口拒绝请求或服务暂时异常')
                if code is not None and 300 <= code < 400:
                    reason = '接口返回重定向，为保护 key 未自动跟随；请填写最终 API 根地址'
                result_box.update(status='error', http_status=code, message=f'HTTP {code}：{reason}')
                return
            content = bytearray()
            for part in resp.iter_content(chunk_size=1024):
                content.extend(part)
                if len(content) > 65536:
                    raise ValueError('测试响应过长')
            data = json.loads(content)
            if cfg['provider'] == 'anthropic':
                parse_anthropic_message(data)
            else:
                parse_chat_completion_json(data)
            result_box.update(status='success', http_status=200,
                              message='HTTP 200：认证与接口响应正常（不代表棋力或所有参数均兼容）')
        except requests.exceptions.Timeout:
            result_box.update(status='error', http_status=None, message=f'连接测试超时（最长 {timeout} 秒），请检查网络、地址或稍后再试')
        except requests.exceptions.SSLError:
            result_box.update(status='error', http_status=None, message='TLS 证书校验失败，未关闭证书校验，请修复证书/代理')
        except requests.exceptions.RequestException:
            result_box.update(status='error', http_status=None, message='网络连接失败，请检查 API 地址、DNS 与代理')
        except (ValueError, TypeError, json.JSONDecodeError):
            result_box.update(status='error', http_status=locals().get('code'), message='返回格式不兼容：仅支持 OpenAI Chat Completions 或 Anthropic Messages JSON；响应不能过长')
        except Exception:
            result_box.update(status='error', http_status=None, message='连接测试内部出错，请查看终端并稍后重试')
        finally:
            done.set()

    threading.Thread(target=probe, daemon=True, name='api-connection-test').start()
    if not done.wait(timeout):
        return jsonify(status='error', http_status=None, message=f'连接测试超时（{timeout} 秒）；远端请求可能仍在结束中，请勿频繁重试')
    return jsonify(result_box)


@app.route('/api/resume_battle', methods=['POST'])
@app.route('/api/retry_now', methods=['POST'])
def resume_battle():
    """「立即重试 / 继续对战」：
    - 对战线程还在（正在网络重连或等模型）：取消等待，立刻重新请求当前一方；
    - 对战线程已停（暂停、异常、服务重启前的线程丢失）：从当前局面、轮到的一方重新开线程。
    """
    battle = current_battle
    if battle is None:
        return jsonify({"status": "error", "message": "没有可继续的对局（服务可能重启过），请重新开始对战"}), 400
    if battle.status == "finished":
        return jsonify({"status": "error", "message": "对局已经结束", "state": battle_snapshot(battle)}), 400
    if battle.status == "stopped":
        return jsonify({"status": "error", "message": "对局已停止，请重新开始对战"}), 400
    with state_lock:
        actor = player_of(battle, battle.game.current_player)
        if getattr(actor, "kind", "ai") == "human" and getattr(battle, "phase", "") in ("human_turn", "applying"):
            return jsonify({
                "status": "success",
                "action": "human_turn",
                "message": "现在是棋盘上走棋，不用重试模型",
                "current_player": battle.game.current_player,
                "move_count": len(battle.game.move_history),
                "state": battle_snapshot(battle),
            })
        if battle.status == "playing" and loop_alive(battle):
            battle.wake_event.set()
            cancel_inflight(battle)
            print("用户点击「立即重试」：取消当前等待，马上重新请求")
            set_phase(battle, "thinking", "已立即重试，等待模型回复")
            action = "retry_now"
            message = "已立即重试当前一方"
        else:
            # 旧线程若正在退出，最多等 2 秒
            t = getattr(battle, "loop_thread", None)
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
            battle.status = "playing"
            battle.pause_reason = None
            battle.wake_event.clear()
            recorder = _recorder(battle)
            if recorder:
                recorder.set_status("playing")
            set_phase(battle, "resuming", "")
            start_loop(battle)
            print("用户点击「继续对战」，从当前局面恢复")
            action = "resumed"
            message = "对局已继续"
    recorder = _recorder(battle)
    return jsonify({
        "status": "success",
        "action": action,
        "message": message,
        "current_player": battle.game.current_player,
        "move_count": len(battle.game.move_history),
        "record_path": recorder.path if recorder else None,
        "state": battle_snapshot(battle),
    })


@app.route('/api/stop_battle', methods=['POST'])
def stop_battle():
    """停止对战：立即生效（取消正在进行的模型请求和重连等待）"""
    with state_lock:
        battle = _stop_current()
        if battle is not None and battle.status == "stopped":
            set_phase(battle, "stopped", "对战已停止")
    return jsonify({"status": "success", "message": "对战已停止", "state": battle_snapshot(battle)})


@app.route('/api/reset_battle', methods=['POST'])
def reset_battle():
    """重置：停止并丢弃当前对局（棋谱文件保留在 games/）"""
    global current_battle
    with state_lock:
        _stop_current()
        current_battle = None
    socketio.emit("battle_state", battle_snapshot(None))
    return jsonify({"status": "success", "message": "已重置"})


@app.route('/api/get_battle_status', methods=['GET'])
def get_battle_status():
    """获取对战状态（页面刷新/重连后恢复界面用）"""
    return jsonify(battle_snapshot(current_battle))


if __name__ == '__main__':
    try:
        print("正在启动弈台（中国象棋 / 五子棋）...")
        print("访问地址: http://localhost:5003")
        print(f"对局记录目录: {GAMES_DIR}")
        # debug=True 会开自动重载，改文件时会杀掉正在下的对局线程；这里关掉重载，保留调试输出。
        socketio.run(app, debug=True, use_reloader=False, host='127.0.0.1', port=5003, allow_unsafe_werkzeug=True)
    except Exception as e:
        print(f"启动应用时发生错误: {e}")
        traceback.print_exc()
