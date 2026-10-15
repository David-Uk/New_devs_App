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

    FIX (see FINDINGS.md, issue 1.3 - tenant-blind data):
    Cached payloads are validated against the requesting tenant before being
    served (defense-in-depth). The old code served data that was keyed/fabricated
    by property_id only (the hardcoded mock returned tenant-a's figures to
    tenant-b); a payload whose embedded tenant_id doesn't match is now discarded
    and recomputed instead of served.
    """
    # FIX (FINDINGS.md 1.1): tenant_id added to the cache key so revenue
    # results are cached per tenant+property instead of per property alone.
    # Old key: "revenue:{property_id}"  ->  New key: "revenue:{tenant_id}:{property_id}"
    cache_key = f"revenue:{tenant_id}:{property_id}"
    
    # Try to get from cache (now safe: key includes tenant_id, no cross-tenant hits)
    cached = await redis_client.get(cache_key)
    if cached:
        payload = json.loads(cached)
        # FIX (FINDINGS.md 1.3): never serve a payload built for another tenant
        # (e.g. stale entries from the old property-only key scheme, or any future
        # mis-keyed write). Mismatched tenant -> drop it and recompute the truth.
        if payload.get("tenant_id") == tenant_id:
            return payload
        await redis_client.delete(cache_key)
    
    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue
    
    # Calculate revenue
    result = await calculate_total_revenue(property_id, tenant_id)
    
    # Cache the result for 5 minutes under the tenant-scoped key (FIX FINDINGS.md 1.1),
    # so one tenant's totals can never be served to another tenant.
    await redis_client.setex(cache_key, 300, json.dumps(result))
    
    return result
