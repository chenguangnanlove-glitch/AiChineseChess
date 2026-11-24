"""同机玩家。不保存密钥，也不会发起任何模型请求。"""


class HumanPlayer:
    kind = "human"

    def __init__(self, display_name: str):
        self.display_name = display_name or "玩家"
        self.model_name = "human"
        self.api_key = ""
        self.base_url = ""
        self.provider = "human"
        self.move_count = 0
        self.total_thinking_time = 0
        self.socketio = None
        self.battle_id = None

    def cancel_call(self, token=None):
        return None

    def begin_call(self, token):
        return None

    def get_move(self, *args, **kwargs):
        raise RuntimeError("同机玩家不调用模型")

    def get_stats(self):
        return {
            "display_name": self.display_name,
            "model_name": self.model_name,
            "move_count": self.move_count,
            "total_thinking_time": 0,
            "avg_thinking_time": 0,
        }
