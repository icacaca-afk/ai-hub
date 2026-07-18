# AI Hub — RetryStage
# V1.0.2: 失败重试 Stage（ADR-0022 ChatGPT 9.9/10 FINAL APPROVED）
#
# 验证 Pipeline 扩展性：第一个非 metrics Stage，证明 Pipeline 不需要修改就能加新能力。
#
# ChatGPT 唯一采纳调整（9.9/10）：
#   is_retryable 默认从"所有失败可重试"改为"仅安全可重试"
#   （网络异常/超时/5xx/限流/429）
#
# ChatGPT 2 项非阻塞原则建议（采纳）：
#   ① RetryStage SHOULD only retry idempotent bridge executions
#   ② Attempt Metadata (V1.1 评估，V1.0.2 不实施)
#
# 关键约束（来自 Runtime Contract §9.1.3）：
#   - MUST NOT 修改 routing 决策（ctx.provider / ctx.bridge 保持不变）
#   - MUST 重新调用 ctx.bridge.run(ctx.task) 触发重试
#   - MUST 用 ctx.with_bridge_result(new_br) 更新上下文
#   - default is_retryable: 仅网络/超时/5xx/限流
#   - MUST NOT 重试永久错误（401/403/404/参数错误等）
#   - failure: pass（不抛异常，不污染主链路）
#
# 4 种退避策略（Stable API 字符串）：
#   - immediate: 0
#   - fixed: initial_delay_ms
#   - linear: initial_delay_ms * attempt
#   - exponential (default): initial_delay_ms * 2^(attempt-1)
#
# Default Retry Policy（ChatGPT 9.95/10 文档化建议）：
#   Priority 1: raw.status_code（如果 raw 是 dict）
#     - 5xx 全部 (500/502/503/504) 重试
#     - 429 限流 重试
#     - 其他 status_code 不重试
#   Priority 2: error message 文本模式匹配
#     - 网络异常：TimeoutError / ConnectionError / URL Error
#     - 限流：RateLimitError / "rate limit" / "too many requests"
#     - 5xx：ServiceUnavailableError / InternalServerError / 等
#     - "HTTP 5xx" / "HTTP 429"
#   Priority 3: 保守不重试
#     - 401 / 403 / 404 / 400 / quota / validation
#     - 无明确错误信息
#     - 用户可自定义 is_retryable 完全覆盖默认行为
#
# Stage 顺序（V1.0+ 约定）：
#   post_bridge_stages = [RetryStage, MetricsStage]
#   - 先重试（失败可重试）
#   - 再 metrics（提取最终 server_metrics）
#
# API Stability: Experimental

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from core.bridge import BridgeResult
from planner.pipeline import ExecutionContext
from planner.stage_descriptor import StageDescriptor

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 默认安全重试：可重试错误模式（ChatGPT 9.9/10 唯一调整）
# ─────────────────────────────────────────────────────────────

# 错误文本模式：大小写不敏感子串匹配
# 来源：LLM Provider 常见网络/限流错误关键词
SAFE_RETRY_ERROR_PATTERNS = (
    # 网络异常
    "TimeoutError",
    "ConnectionError",
    "Connection refused",
    "Connection reset",
    "URL Error",
    "Timeout after",
    # 限流
    "RateLimitError",
    "rate limit",
    "too many requests",
    # 5xx 服务端错误
    "ServiceUnavailableError",
    "InternalServerError",
    "BadGatewayError",
    "GatewayTimeoutError",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "HTTP 429",
)


def _default_retryable(br: BridgeResult) -> bool:
    """默认安全重试策略：仅网络/超时/5xx/限流可重试。

    设计依据（ChatGPT 9.9/10 唯一调整）：
    - LLM Provider 很多失败根本不会因为 Retry 而恢复
      - 401 Unauthorized: api key 无效
      - 403 Forbidden: 权限不足
      - 404 Not Found: model 不存在
      - 400 Bad Request: 参数错误
      - quota exhausted: 配额耗尽
      - validation: 输入验证失败
    - 这些错误重试只是浪费时间，失败原因不会因重试恢复
    - 默认"安全可重试"更符合生产环境

    覆盖能力（用户自定义）：
        RetryStage(is_retryable=lambda br: True)  # 重试所有错误

    Args:
        br: BridgeResult 来自前一次 bridge.run()

    Returns:
        True 表示可重试，False 表示不重试
    """
    if br.success:
        return False

    # 1. 检查 raw.status_code（如果 raw 是 dict，APIBridge HTTPError 时 raw=error_body 字符串）
    if isinstance(br.raw, dict):
        status_code = br.raw.get("status_code")
        if status_code is not None:
            # 5xx 全部 + 429 限流
            return status_code >= 500 or status_code == 429

    # 2. 检查 error 文本模式匹配
    error_text = (br.error or "").lower()
    for pattern in SAFE_RETRY_ERROR_PATTERNS:
        if pattern.lower() in error_text:
            return True

    # 3. 无明确错误信息时, 不重试（保守）
    return False


# ─────────────────────────────────────────────────────────────
# 退避策略计算（纯函数，便于测试）
# ─────────────────────────────────────────────────────────────

def compute_backoff_delay(
    backoff: str,
    attempt: int,
    initial_delay_ms: int,
    max_delay_ms: int,
) -> int:
    """计算第 N 次重试的退避延迟（毫秒）。

    Args:
        backoff: 退避策略（immediate/fixed/linear/exponential）
        attempt: 重试序号（1-indexed）
        initial_delay_ms: 初始延迟（毫秒）
        max_delay_ms: 最大延迟上限（毫秒）

    Returns:
        延迟毫秒数（0 表示立即重试）

    Raises:
        ValueError: backoff 不在 4 种策略中
    """
    if backoff == "immediate":
        return 0
    elif backoff == "fixed":
        delay = initial_delay_ms
    elif backoff == "linear":
        delay = initial_delay_ms * attempt
    elif backoff == "exponential":
        delay = initial_delay_ms * (2 ** (attempt - 1))
    else:
        raise ValueError(
            f"Invalid backoff: {backoff}. "
            f"Must be one of: immediate, fixed, linear, exponential"
        )

    return min(delay, max_delay_ms)


# ─────────────────────────────────────────────────────────────
# RetryStage
# ─────────────────────────────────────────────────────────────

# Type alias for retryable predicate
RetryablePredicate = Callable[[BridgeResult], bool]

# 合法 backoff 策略（Stable API 字符串）
VALID_BACKOFFS = ("immediate", "fixed", "linear", "exponential")


class RetryStage:
    """Post-bridge Stage: 失败重试（ADR-0022）。

    在 ExecutionPipeline.post_bridge_stages 中位置：
        [RetryStage, MetricsStage]  # 推荐顺序（先重试，再 metrics）

    行为契约：
        1. ctx.bridge_result.success = True → pass（不重试）
        2. ctx.bridge_result.success = False 且 is_retryable = False → pass（不重试）
        3. ctx.bridge_result.success = False 且 is_retryable = True → 重试
           循环 max_retries 次，每次：
             a. sleep compute_backoff_delay(attempt)
             b. 调 ctx.bridge.run(ctx.task) → new_br
             c. new_br.success → 用 new_br 替换 ctx.bridge_result, return
             d. is_retryable(new_br) = False → 用 new_br 替换 ctx.bridge_result, return
             e. 否则继续下一次重试
        4. 重试 max_retries 次后仍失败 → return ctx（保留最后失败 result）

    关键不变量（来自 Runtime Contract §9.1.3）：
        - MUST NOT 修改 ctx.provider / ctx.bridge（routing 不变）
        - MUST NOT 修改 ctx.task
        - MUST NOT 修改 ctx.stop
        - MUST 用 ctx.with_bridge_result(new_br) 更新 ctx
        - MUST NOT 抛异常（bridge.run 异常时 continue 重试）

    API Stability: Experimental
    """

    # V1.0.6: 显式 StageDescriptor (ADR-0026 ChatGPT 9.94/10 Critical Q7)
    descriptor = StageDescriptor(
        name="retry",
        version=1,
        role="retry",
        capabilities=frozenset({"retries"}),
        idempotent=False,  # 重试 -> 多次副作用
        has_side_effects=True,
        always_run_after_stop=False,
        description="Retries failed bridge execution",
        owner="ai-hub",
        experimental=False,
    )

    def __init__(
        self,
        max_retries: int = 3,
        backoff: str = "exponential",
        initial_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        is_retryable: Optional[RetryablePredicate] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        """构造 RetryStage。

        Args:
            max_retries: 最大重试次数（默认 3，0 表示不重试）
            backoff: 退避策略（immediate/fixed/linear/exponential，默认 exponential）
            initial_delay_ms: 初始延迟（毫秒，默认 100）
            max_delay_ms: 最大延迟上限（毫秒，默认 5000）
            is_retryable: 自定义重试判定函数（默认 _default_retryable：仅安全可重试）
            sleep: 测试注入的 sleep 函数（默认 time.sleep）

        Raises:
            ValueError: 参数非法
        """
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        if backoff not in VALID_BACKOFFS:
            raise ValueError(
                f"Invalid backoff: {backoff}. "
                f"Must be one of: {', '.join(VALID_BACKOFFS)}"
            )
        if initial_delay_ms < 0:
            raise ValueError(f"initial_delay_ms must be >= 0, got {initial_delay_ms}")
        if max_delay_ms < initial_delay_ms:
            raise ValueError(
                f"max_delay_ms ({max_delay_ms}) must be >= "
                f"initial_delay_ms ({initial_delay_ms})"
            )

        self.max_retries = max_retries
        self.backoff = backoff
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        self.is_retryable = is_retryable or _default_retryable
        # 测试可注入的 sleep（避免真实等待）
        self._sleep = sleep or time.sleep
        self._name = "retry"
        self._attempt_count = 0  # 累计重试次数（测试用）

    @property
    def name(self) -> str:
        return self._name

    @property
    def attempt_count(self) -> int:
        """累计重试次数（V1.0.2 暂不进 ctx，V1.1 进入 Result.metadata）。"""
        return self._attempt_count

    def reset(self) -> None:
        """重置累计重试次数（测试隔离用）。"""
        self._attempt_count = 0

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """处理 ctx: 失败时重试，成功后用新 result 替换。

        短路条件（直接 pass，不重试）：
            - ctx.stop = True（已被前面 Stage 短路）
            - ctx.bridge_result is None（base_execute 失败）
            - ctx.bridge is None（RouteStage 没选 bridge）
            - ctx.bridge_result.success = True（成功不重试）
            - max_retries = 0（不重试）
            - is_retryable(br) = False（默认仅安全错误重试）

        Returns:
            新的 ExecutionContext（bridge_result 可能是重试后的最终结果）
        """
        # 短路检查
        if ctx.stop or ctx.bridge_result is None or ctx.bridge is None:
            return ctx

        br = ctx.bridge_result
        if br.success:
            return ctx  # 成功不重试

        if self.max_retries == 0:
            return ctx  # 关闭重试

        if not self.is_retryable(br):
            logger.debug(
                "RetryStage: bridge_result not retryable, skip. error=%s",
                br.error,
            )
            return ctx  # 不可重试

        # 重试循环
        for attempt in range(1, self.max_retries + 1):
            delay = compute_backoff_delay(
                self.backoff,
                attempt,
                self.initial_delay_ms,
                self.max_delay_ms,
            )

            if delay > 0:
                self._sleep(delay / 1000.0)

            self._attempt_count += 1

            try:
                new_br = ctx.bridge.run(ctx.task)
            except Exception as e:
                # bridge.run 抛异常 → 继续下一次重试（不污染主链路）
                # ChatGPT 9.95/10 Q4 建议: 包含 provider/attempt/exception type/message
                logger.warning(
                    "RetryStage provider=%s attempt=%d/%d raised %s: %s",
                    ctx.provider.name if ctx.provider else "<unknown>",
                    attempt, self.max_retries,
                    type(e).__name__, str(e),
                )
                continue

            if new_br.success:
                logger.info(
                    "RetryStage succeeded on attempt %d/%d",
                    attempt, self.max_retries,
                )
                return ctx.with_bridge_result(new_br)

            # 失败后再判断
            if not self.is_retryable(new_br):
                logger.debug(
                    "RetryStage: attempt %d not retryable, stop. error=%s",
                    attempt, new_br.error,
                )
                return ctx.with_bridge_result(new_br)

            logger.debug(
                "RetryStage attempt %d/%d failed, will retry. error=%s",
                attempt, self.max_retries, new_br.error,
            )

        # 重试用尽，保留最后失败 result
        logger.warning(
            "RetryStage exhausted %d retries, giving up.",
            self.max_retries,
        )
        return ctx
