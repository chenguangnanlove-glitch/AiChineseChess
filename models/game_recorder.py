"""将对局着法实时写入项目 games/ 目录，中断时不丢失已下棋谱。"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _safe_name(text: str) -> str:
    text = re.sub(r"[^\w.\-+]+", "-", (text or "").strip())
    text = text.strip("-") or "model"
    return text[:40]


class GameRecorder:
    """每步写一次完整 JSON（原子替换），便于事后做分析视频。"""

    def __init__(self, red_player, black_player, games_dir: str):
        os.makedirs(games_dir, exist_ok=True)
        started = datetime.now(TZ)
        red_name = _safe_name(getattr(red_player, "model_name", "") or getattr(red_player, "display_name", "red"))
        black_name = _safe_name(getattr(black_player, "model_name", "") or getattr(black_player, "display_name", "black"))
        stamp = started.strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(games_dir, f"{stamp}-{red_name}-vs-{black_name}.json")
        self.data = {
            "started_at": started.isoformat(timespec="seconds"),
            "updated_at": started.isoformat(timespec="seconds"),
            "timezone": "Asia/Shanghai",
            "red": {
                "display_name": getattr(red_player, "display_name", ""),
                "model_name": getattr(red_player, "model_name", ""),
            },
            "black": {
                "display_name": getattr(black_player, "display_name", ""),
                "model_name": getattr(black_player, "model_name", ""),
            },
            "status": "playing",
            "result": None,
            "pause_reason": None,
            "moves": [],
        }
        self.save()

    def add_move(self, *, player_color: str, player_name: str, model_name: str,
                 move: str, thinking: str = "", analysis: str = "",
                 strategy: str = "", board_state: str = "", thinking_time: float = None, **extra):
        entry = {
            "n": len(self.data["moves"]) + 1,
            "player": player_color,
            "player_name": player_name,
            "model": model_name,
            "move": move,
            "thinking": thinking or "",
            "analysis": analysis or "",
            "strategy": strategy or "",
            "thinking_time": thinking_time,
            "time": now_iso(),
            "board_state": board_state or "",
        }
        entry.update(extra)
        self.data["moves"].append(entry)
        self.data["status"] = "playing"
        self.save()

    def set_status(self, status: str, reason: str = None, result=None):
        self.data["status"] = status
        if status == "playing":
            self.data["pause_reason"] = None
        if reason is not None:
            self.data["pause_reason"] = reason
        if result is not None:
            self.data["result"] = result
        if status in ("finished", "stopped", "error"):
            self.data["ended_at"] = now_iso()
        self.save()

    def save(self):
        self.data["updated_at"] = now_iso()
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.path)
