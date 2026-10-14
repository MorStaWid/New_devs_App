import json
from typing import Dict, Any
import os

try:
    import redis.asyncio as redis
    _redis_available = True
except ImportError:  # local verification without redis installed
    redis = None  # type: ignore
    _redis_available = False

# Initialize Redis client (typically configured centrally).
# Lazily created so importing this module never requires a live server.
_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is None and _redis_available:
        _redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    return _redis_client


# Backwards-compatible module-level client (None when redis isn't installed).
redis_client = get_redis_client()


def build_revenue_cache_key(property_id: str, tenant_id: str) -> str:
    """Tenant-isolated cache key. NEVER key revenue by property_id alone.

    Both tenants share `prop-001` (see database/seed.sql), so a bare
    `revenue:{property_id}` key serves one tenant's totals to the other.
    """
    return f"revenue:{tenant_id}:{property_id}"


async def invalidate_revenue_cache(property_id: str, tenant_id: str) -> None:
    """Delete a tenant's cached revenue summary (e.g. after new bookings)."""
    client = get_redis_client()
    if client is None:
        return
    await client.delete(build_revenue_cache_key(property_id, tenant_id))

async def get_revenue_summary(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    Cache is isolated per (tenant_id, property_id) to prevent cross-tenant leaks.
    """
    cache_key = build_revenue_cache_key(property_id, tenant_id)

    client = get_redis_client()
    # Try to get from cache (skip silently when Redis is unavailable)
    if client is not None:
        cached = await client.get(cache_key)
        if cached:
            return json.loads(cached)

    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue

    # Calculate revenue
    result = await calculate_total_revenue(property_id, tenant_id)

    # Cache the result for 5 minutes
    if client is not None:
        await client.setex(cache_key, 300, json.dumps(result))

    return result
