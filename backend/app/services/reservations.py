from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List

async def calculate_monthly_revenue(property_id: str, month: int, year: int, db_session=None) -> Decimal:
    """
    Calculates revenue for a specific month.
    """

    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)
        
    print(f"DEBUG: Querying revenue for {property_id} from {start_date} to {end_date}")

    # SQL Simulation (This would be executed against the actual DB)
    query = """
        SELECT SUM(total_amount) as total
        FROM reservations
        WHERE property_id = $1
        AND tenant_id = $2
        AND check_in_date >= $3
        AND check_in_date < $4
    """
    
    # In production this query executes against a database session.
    # result = await db.fetch_val(query, property_id, tenant_id, start_date, end_date)
    # return result or Decimal('0')
    
    return Decimal('0') # Placeholder for now until DB connection is finalized

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.

    FIX (FINDINGS.md 1.2 + 1.3): the old implementation built a new DatabasePool() per
    request from nonexistent settings.supabase_db_* fields, so initialization always
    failed; a bare `except` then swallowed the error and returned HARDCODED MOCK
    revenue with HTTP 200. The mock was tenant-blind (FINDINGS.md 1.3): it was keyed
    by property_id only, so tenant-b received tenant-a's fabricated figures
    ('prop-001' -> mock 1000.00/3 while tenant-b reality is 0.00/0, and tenant-a
    reality is 2250.000/4). The pool URL now comes from settings.database_url, the
    shared global pool is reused, the mock dict is deleted entirely, and all results
    come from SQL that filters on BOTH property_id AND tenant_id - DB failures now
    propagate to the caller instead of being masked by fabricated numbers.
    """
    # FIX (FINDINGS.md 1.2): reuse the shared global pool (database_pool.db_pool)
    # instead of constructing a new DatabasePool() per request (never disposed).
    from app.core.database_pool import db_pool
    from sqlalchemy import text

    # FIX (FINDINGS.md 1.2): initialize the shared pool (idempotent, retries after
    # failure). Previously this always failed due to the supabase_db_* settings bug.
    await db_pool.initialize()
    if not db_pool.session_factory:
        # FIX (FINDINGS.md 1.2 + 1.3): surface the failure loudly - no more silent
        # fallback to the hardcoded mock_data dict, which both hid real revenue
        # errors (1.2) and was keyed by property_id only, serving one tenant's
        # fabricated figures to another (1.3).
        raise RuntimeError(
            "Database pool not available - cannot calculate revenue "
            f"(property={property_id}, tenant={tenant_id})"
        )

    async with db_pool.get_session() as session:
        query = text("""
            SELECT 
                property_id,
                SUM(total_amount) as total_revenue,
                COUNT(*) as reservation_count
            FROM reservations 
            WHERE property_id = :property_id AND tenant_id = :tenant_id
            GROUP BY property_id
        """)

        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id
        })
        row = result.fetchone()

        if row:
            total_revenue = Decimal(str(row.total_revenue))
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": str(total_revenue),
                "currency": "USD",
                "count": row.reservation_count
            }
        else:
            # No reservations found for this property
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": "0.00",
                "currency": "USD",
                "count": 0
            }
