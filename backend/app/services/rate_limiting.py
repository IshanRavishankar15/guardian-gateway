from dataclasses import dataclass
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import redis_client
from app.db.models import RateLimitPolicy


TOKEN_BUCKET_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at_ms')
local tokens = tonumber(state[1]) or capacity
local updated_at_ms = tonumber(state[2]) or now_ms
tokens = math.min(capacity, tokens)

if now_ms > updated_at_ms then
  tokens = math.min(capacity, tokens + ((now_ms - updated_at_ms) / 1000) * refill_rate)
end

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at_ms', now_ms)
local ttl_ms = math.ceil((capacity / refill_rate) * 1000) + 1000
redis.call('PEXPIRE', KEYS[1], ttl_ms)
local retry_after = 0
if allowed == 0 then
  retry_after = math.ceil((1 - tokens) / refill_rate)
end
return {allowed, math.floor(tokens), retry_after}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


async def find_policy(
    session: AsyncSession, client_id: uuid.UUID, route_id: uuid.UUID
) -> RateLimitPolicy | None:
    """Choose one applicable policy by specificity: client+route, client, route, global."""
    result = await session.scalars(
        select(RateLimitPolicy)
        .where(
            RateLimitPolicy.enabled.is_(True),
            ((RateLimitPolicy.client_id == client_id) | RateLimitPolicy.client_id.is_(None)),
            ((RateLimitPolicy.route_id == route_id) | RateLimitPolicy.route_id.is_(None)),
        )
        .order_by(
            RateLimitPolicy.client_id.is_not(None).desc(),
            RateLimitPolicy.route_id.is_not(None).desc(),
            RateLimitPolicy.updated_at.desc(),
            RateLimitPolicy.id,
        )
    )
    return result.first()


def bucket_key(policy: RateLimitPolicy, client_id: uuid.UUID, route_id: uuid.UUID) -> str:
    if policy.client_id is not None and policy.route_id is not None:
        scope = f"client:{client_id}:route:{route_id}"
    elif policy.client_id is not None:
        scope = f"client:{client_id}"
    elif policy.route_id is not None:
        scope = f"route:{route_id}"
    else:
        scope = "global"
    return f"guardian:rate-limit:{policy.id}:{scope}"


async def consume_token(
    policy: RateLimitPolicy, client_id: uuid.UUID, route_id: uuid.UUID
) -> RateLimitDecision:
    result = await redis_client.eval(
        TOKEN_BUCKET_SCRIPT,
        1,
        bucket_key(policy, client_id, route_id),
        policy.capacity,
        policy.refill_rate,
    )
    allowed, remaining, retry_after = (int(value) for value in result)
    return RateLimitDecision(
        allowed=bool(allowed),
        limit=policy.capacity,
        remaining=max(0, remaining),
        retry_after=max(0, retry_after),
    )
