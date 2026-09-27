class DaikinError(Exception):
    """本体との通信・応答の失敗。rsc は本体が返した結果コード (無ければ None)。"""

    def __init__(self, message: str, *, rsc: int | None = None) -> None:
        super().__init__(message)
        self.rsc = rsc


class DaikinConnectionError(DaikinError):
    """本体へ到達できない (タイムアウト・接続拒否など)。"""
