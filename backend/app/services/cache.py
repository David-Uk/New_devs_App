import json
import redis.asyncio as redis
from typing import Dict, Any
import os

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def get_revenue_summary(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.

    FIX (see FINDINGS.md, issue 1.1 - cross-tenant cache leak):
    The cache key is now tenant-scoped.
      Before (buggy): cache_key = f"revenue:{property_id}"
      After  (fixed):  cache_key = f"revenue:{tenant_id}:{property_id}"
    Because multiple tenants can own the same property_id (seed.sql gives
    'prop-001' to both tenant-a "Sunset Properties" and tenant-b "Ocean Rentals"),
    the old key let whichever tenant queried first poison the cache for the
    other tenant for up to 300 seconds (Client B's privacy report).
    """
    # FIX (FINDINGS.md 1.1): tenant_id added to the cache key so revenue
    # results are cached per tenant+property instead of per property alone.
    # Old key: "revenue:{property_id}"  ->  New key: "revenue:{tenant_id}:{property_id}"
    cache_key = f"revenue:{tenant_id}:{property_id}"
    
    # Try to get from cache (now safe: key includes tenant_id, no cross-tenant hits)
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue
    
    # Calculate revenue
    result = await calculate_total_revenue(property_id, tenant_id)
    
    # Cache the result for 5 minutes under the tenant-scoped key (FIX FINDINGS.md 1.1),
    # so one tenant's totals can never be served to another tenant.
    await redis_client.setex(cache_key, 300, json.dumps(result))
    
    return result
