from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from decimal import Decimal, InvalidOperation
from app.services.cache import get_revenue_summary
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()

@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    
    tenant_id = getattr(current_user, "tenant_id", "default_tenant") or "default_tenant"
    
    revenue_data = await get_revenue_summary(property_id, tenant_id)
    
    # FIX (FINDINGS.md 1.4): keep money exact end-to-end. The old line
    # `total_revenue_float = float(revenue_data['total'])` converted the exact
    # NUMERIC(10,3) decimal into an IEEE-754 double; JSON + JS rounding then drifted
    # by a cent ("totals slightly off" from finance). The API now returns the exact
    # decimal as a string - the frontend rounds for display with integer math only.
    try:
        total_exact = Decimal(str(revenue_data['total']))
    except InvalidOperation:
        # Surface corrupt/non-numeric revenue data instead of coercing it to a float.
        raise HTTPException(
            status_code=500,
            detail=f"Invalid revenue total for property {property_id}: {revenue_data['total']!r}"
        )
    
    return {
        "property_id": revenue_data['property_id'],
        "total_revenue": str(total_exact),
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count']
    }
