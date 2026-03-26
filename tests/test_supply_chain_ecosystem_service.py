from datetime import datetime, timedelta, timezone

from services.supply_chain_ecosystem_service import (
    OrderStatus,
    SupplyChainEcosystemService,
)


def test_generate_supplier_pnl_preserves_accounting_invariants():
    supplier_id = "SUP-1"
    now = datetime.now(timezone.utc)
    report_date = now.isoformat()
    service = SupplyChainEcosystemService(
        suppliers_store={
            supplier_id: {
                "company_name": "Parity Pharmacy",
                "average_rating": 4.9,
                "on_time_delivery_rate": 98.0,
                "dispute_count": 0,
            }
        },
        orders_store={
            "ORD-1": {
                "supplier_id": supplier_id,
                "status": OrderStatus.COMPLETED.value,
                "total_amount": 100.0,
                "commission": 10.0,
                "payment_processing_fee": 0.335,
                "supplier_payout": 80.0,
                "created_date": report_date,
                "updated_date": report_date,
                "completed_date": report_date,
            }
        },
    )

    result = service.generate_supplier_pnl(
        supplier_id,
        period_start=(now - timedelta(days=1)).isoformat(),
        period_end=(now + timedelta(days=1)).isoformat(),
    )
    report = result["report"]

    assert report["payment_processing_fees"] == 0.34
    assert report["total_deductions"] == 10.34
    assert report["net_payout"] == 89.66
    assert report["net_payout"] == round(report["net_sales"] - report["total_deductions"], 2)
    assert report["total_deductions"] == round(
        report["platform_commission"] + report["payment_processing_fees"] + report["other_fees"],
        2,
    )
