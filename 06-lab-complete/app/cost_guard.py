"""Cost guard (tiêu chí 8) — theo dõi chi phí LLM trong Redis."""
import threading
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_memory_lock = threading.Lock()
_memory_spend: dict[str, float] = {}


def _budget_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _effective_budget() -> float:
    return min(settings.daily_budget_usd, settings.monthly_budget_usd)


def check_budget() -> None:
    """Gọi trước khi gọi LLM. Hết budget -> raise HTTPException(status_code=402)."""
    key = _budget_key()
    budget = _effective_budget()

    if r is not None:
        try:
            current = float(r.get(key) or 0.0)
        except RedisError as exc:
            raise HTTPException(
                status_code=503,
                detail="Cost guard storage unavailable",
            ) from exc
    else:
        with _memory_lock:
            current = _memory_spend.get(key, 0.0)

    if current >= budget:
        raise HTTPException(
            status_code=402,
            detail="Budget limit exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi sau khi gọi LLM. Cộng chi phí vào tổng và trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K
    key = _budget_key()

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(key, cost)
            pipe.expire(key, 48 * 3600)
            pipe.execute()
        except RedisError:
            pass
    else:
        with _memory_lock:
            _memory_spend[key] = _memory_spend.get(key, 0.0) + cost

    return cost
