"""天气模块错误上报。

子模块不依赖主仓库。主仓库在加载 WeatherAgent 时注册 reporter，
未注册时只写日志，方便单独运行天气接口。
"""
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ErrorReporter = Callable[[int, str, Any], None]
_reporter: Optional[ErrorReporter] = None


def set_error_reporter(reporter: Optional[ErrorReporter]) -> None:
    global _reporter
    _reporter = reporter


def report_error(code: int, message: str, detail: Any = None) -> None:
    if _reporter is not None:
        _reporter(code, message, detail)
        return
    logger.error("weather error %s: %s", code, message, exc_info=detail)
