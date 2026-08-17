"""熔断器（Circuit Breaker）。

用途：当某个数据源（Provider）在短时间内连续失败达到阈值时，
主动"熔断"——在冷却时间内不再向其发起请求，而是直接快速失败，
把请求交给下一个备用数据源；冷却结束后进入"半开"状态试探一次，
成功则恢复、失败则继续熔断。

这样可以避免：
1. 对已经挂掉/被限流的数据源做无意义的重试，浪费时间；
2. 雪崩式地把所有并发都砸在唯一一个也开始不稳定的源上。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class CircuitState(str, Enum):
    CLOSED = "closed"      # 正常放行
    OPEN = "open"          # 已熔断，快速失败
    HALF_OPEN = "half_open"  # 冷却结束，允许一次试探


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5        # 连续失败多少次后熔断
    cooldown_seconds: float = 30.0    # 熔断后冷却时长
    half_open_max_calls: int = 1      # 半开状态允许的试探次数
    success_threshold: int = 1        # 半开状态下连续成功多少次后恢复


class CircuitBreaker:
    """基于连续失败计数的简单熔断器（线程安全用实例单线程即可，本服务为单进程异步）。"""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._half_open_calls = 0
        self._opened_at = 0.0
        self._last_failure_at = 0.0

    @property
    def state(self) -> CircuitState:
        # 冷却时间到了，从 OPEN 转 HALF_OPEN
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self.config.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._half_open_successes = 0
        return self._state

    def allow(self) -> bool:
        """当前是否允许发起请求。"""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            self._half_open_calls += 1
            if self._half_open_successes >= self.config.success_threshold:
                self._reset()
        else:
            # CLOSED 状态下成功：清零连续失败计数
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        self._last_failure_at = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            self._trip()
        elif self._consecutive_failures >= self.config.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._half_open_successes = 0
        self._half_open_calls = 0

    def _reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._half_open_calls = 0

    def force_open(self) -> None:
        self._trip()

    def force_close(self) -> None:
        self._reset()

    def stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self._consecutive_failures,
            "opened_at": self._opened_at,
        }


def with_circuit_breaker(
    breaker: CircuitBreaker,
    func: Callable,
    *args,
    **kwargs,
):
    """在熔断器保护下执行 func。

    - 若熔断器不允许（OPEN），抛出 ProviderError("circuit_open")；
    - func 成功则记录成功并返回结果；
    - func 抛任何异常则记录失败并原样重新抛出。
    """
    if not breaker.allow():
        from .models import ProviderError

        raise ProviderError(breaker.name, "circuit_breaker_open")
    try:
        result = func(*args, **kwargs)
    except Exception:
        breaker.record_failure()
        raise
    breaker.record_success()
    return result
