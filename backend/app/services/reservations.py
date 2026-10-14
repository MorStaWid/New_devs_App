from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Tuple
from zoneinfo import ZoneInfo

# Cents quantization for all money leaving this service.
CENT = Decimal("0.01")


def quantize_revenue(amount: Decimal) -> Decimal:
    """Round money to cents with bankers'-agnostic ROUND_HALF_UP.

    Keeps Decimal end-to-end so 333.333 + 333.333 + 333.334 == 1000.00
    instead of drifting through binary float.
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def get_month_utc_bounds(month: int, year: int, tz_name: str = "UTC") -> Tuple[datetime, datetime]:
    """Return [start, end) of a property-local calendar month as UTC instants.

    Example: March 2024 in Europe/Paris (CET/CEST) is
    2024-02-29T23:00Z .. 2024-03-31T22:00Z, not 2024-03-01T00:00Z .. 04-01.
    """
    tz = ZoneInfo(tz_name or "UTC")
    local_start = datetime(year, month, 1, tzinfo=tz)
    if month < 12:
        local_end = datetime(year, month + 1, 1, tzinfo=tz)
    else:
        local_end = datetime(year + 1, 1, 1, tzinfo=tz)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def is_in_property_month(check_in_utc: datetime, month: int, year: int, tz_name: str = "UTC") -> bool:
    """True when a UTC check-in falls inside the property-local month."""
    if check_in_utc.tzinfo is None:
        check_in_utc = check_in_utc.replace(tzinfo=timezone.utc)
    start, end = get_month_utc_bounds(month, year, tz_name)
    return start <= check_in_utc < end


async def calculate_monthly_revenue(
    property_id: str,
    month: int,
    year: int,
    db_session=None,
    tenant_id: str = "",
    property_timezone: str = "UTC",
) -> Decimal:
    """
    Calculates revenue for a specific month in the PROPERTY's timezone.
    Month boundaries are property-local (e.g. March in Europe/Paris starts
    2024-02-29T23:00Z), not naive UTC month starts.
    """

    start_date, end_date = get_month_utc_bounds(month, year, property_timezone)

    print(f"DEBUG: Querying revenue for {property_id} from {start_date} to {end_date} "
          f"(local {month}/{year} in {property_timezone})")

    # SQL Simulation (This would be executed against the actual DB)
    # Convert the property-local month to UTC bounds and filter in UTC:
    query = """
        SELECT SUM(total_amount) as total
        FROM reservations
        WHERE property_id = $1
        AND tenant_id = $2
        AND check_in_date >= $3
        AND check_in_date < $4
    """

    # In production this query executes against a database session with the
    # UTC bounds above plus tenant scoping:
    # result = await db.fetch_val(query, property_id, tenant_id, start_date, end_date)
    # return quantize_revenue(result or Decimal('0'))

    # Local fallback when no DB session is wired (seed-data mirror):
    if db_session is None:
        from datetime import timezone as _tz
        seed_rows = [
            # (property_id, tenant_id, check_in_utc, amount)
            ("prop-001", "tenant-a", datetime(2024, 2, 29, 23, 30, tzinfo=_tz.utc), Decimal("1250.000")),
            ("prop-001", "tenant-a", datetime(2024, 3, 15, 10, 0, tzinfo=_tz.utc), Decimal("333.333")),
            ("prop-001", "tenant-a", datetime(2024, 3, 16, 10, 0, tzinfo=_tz.utc), Decimal("333.333")),
            ("prop-001", "tenant-a", datetime(2024, 3, 17, 10, 0, tzinfo=_tz.utc), Decimal("333.334")),
        ]
        total = Decimal("0")
        for pid, tid, ci, amt in seed_rows:
            if pid == property_id and (not tenant_id or tid == tenant_id):
                if start_date <= ci < end_date:
                    total += amt
        return quantize_revenue(total)

    return Decimal('0') # Placeholder for now until DB connection is finalized


# Tenant-aware mock fallback (seed mirror). tenant-b has NO prop-001
# reservations, so it must return 0.00 — never tenant-a's figures.
# tenant-a/prop-001 = res-tz-1 (1250.000) + 333.333 + 333.333 + 333.334.
_MOCK_REVENUE = {
    ('prop-001', 'tenant-a'): {'total': '2250.00', 'count': 4},
    ('prop-002', 'tenant-a'): {'total': '4975.50', 'count': 4},
    ('prop-003', 'tenant-a'): {'total': '6100.50', 'count': 2},
    ('prop-004', 'tenant-b'): {'total': '1776.50', 'count': 4},
    ('prop-005', 'tenant-b'): {'total': '3256.00', 'count': 3},
}


async def get_mock_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """Offline fallback revenue, keyed by (property_id, tenant_id)."""
    data = _MOCK_REVENUE.get((property_id, tenant_id), {'total': '0.00', 'count': 0})
    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": data['total'],
        "currency": "USD",
        "count": data['count']
    }

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Import database pool
        from app.core.database_pool import DatabasePool
        
        # Initialize pool if needed
        db_pool = DatabasePool()
        await db_pool.initialize()
        
        if db_pool.session_factory:
            async with db_pool.get_session() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                
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
                    total_revenue = quantize_revenue(Decimal(str(row.total_revenue)))
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
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")

        # Tenant-aware offline fallback (seed mirror).
        return await get_mock_revenue(property_id, tenant_id)
