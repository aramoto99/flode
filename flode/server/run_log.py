"""実行ログ: 実行中にブロックが出したログを GUI の「ログ」タブへ届ける (ADR-0083 §(5))。

``SimulationManager`` は実行スレッドの間だけ :class:`RunLogHandler` を root logger に
付ける。ハンドラは **その実行スレッドから出たレコードだけ** を拾い (同時に走る別の
実行や、サーバ自身のログを混ぜない)、次の 2 系統を対象にする:

- ユーザーブロック (``flode_ws.*``、ADR-0081 の仮想パッケージ): INFO 以上
- flode 本体 (``flode.*``): WARNING 以上 (後片付けの失敗・入れ子 sink の注意など)

ブロック側は標準の ``logging`` を使うだけでよい
(``logging.getLogger(__name__).info("...")``)。ブロックが自分で作ったスレッドから
出したログは拾わない (実行スレッドに戻ってから出すこと)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

#: 1 回の実行で保持・配信するログの上限件数 (超えた分は数だけ数える)。
RUN_LOG_MAX_ENTRIES: Final[int] = 1000
#: 1 件のメッセージの最大文字数 (超えた分は切り詰める)。
RUN_LOG_MAX_MESSAGE_CHARS: Final[int] = 2000
#: ユーザーブロックのモジュールが属する logger 名 (ADR-0081 の仮想パッケージ)。
USER_BLOCK_LOGGER: Final[str] = "flode_ws"
_FLODE_LOGGER: Final[str] = "flode"

LogSink = Callable[[dict[str, Any]], None]


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def ensure_user_block_logging() -> None:
    """ユーザーブロックの INFO ログが作られるよう ``flode_ws`` logger の水準を下げる。

    logger の水準が未設定 (= root の WARNING を継承) だと INFO のレコードは作られず、
    ハンドラに届かない。利用者が明示的に設定している場合は触らない。
    """
    logger = logging.getLogger(USER_BLOCK_LOGGER)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)


class RunLogHandler(logging.Handler):
    """1 回の実行のログを集め、1 件ごとに ``sink`` へ渡す。

    Args:
        thread_id: 対象の実行スレッドの ``threading.get_ident()``。
        current_t: 現在のシミュレーション時刻を返す関数 (各ログに添える)。
        sink: 1 件ごとに wire 形式の dict を受け取る関数 (WS 配信)。
    """

    def __init__(
        self,
        *,
        thread_id: int,
        current_t: Callable[[], float],
        sink: LogSink,
    ) -> None:
        super().__init__(level=logging.INFO)
        self._thread_id = thread_id
        self._current_t = current_t
        self._sink = sink
        self.entries: list[dict[str, Any]] = []
        self.dropped = 0

    def filter(self, record: logging.LogRecord) -> bool:
        """実行スレッドから出た、対象 logger・水準のレコードだけを通す。"""
        if record.thread != self._thread_id:
            return False
        if _under(record.name, USER_BLOCK_LOGGER):
            return record.levelno >= logging.INFO
        if _under(record.name, _FLODE_LOGGER):
            return record.levelno >= logging.WARNING
        return False

    def emit(self, record: logging.LogRecord) -> None:
        """レコードを wire 形式にして保持し、上限内なら ``sink`` へ渡す。"""
        if len(self.entries) >= RUN_LOG_MAX_ENTRIES:
            self.dropped += 1
            return
        try:
            message = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                message = f"{message}: {type(exc).__name__}: {exc}"
            entry = {
                "t": float(self._current_t()),
                "level": record.levelname,
                "logger": record.name,
                "message": message[:RUN_LOG_MAX_MESSAGE_CHARS],
            }
            self.entries.append(entry)
            self._sink(entry)
        except Exception:  # noqa: BLE001 — logging の作法 (ログ処理の失敗で本体を止めない)
            self.handleError(record)
