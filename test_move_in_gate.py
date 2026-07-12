from datetime import date, timedelta
from app.services.move_in_gate_service import MoveInGateService

gate = MoveInGateService(max_keep_days=15)

today = date.today()

tests = [
    ("no admin needed", False, None),
    ("admin needed but no date", True, None),
    ("move in tomorrow", True, today + timedelta(days=1)),
    ("move in 15 days", True, today + timedelta(days=15)),
    ("move in 16 days", True, today + timedelta(days=16)),
    ("past date", True, today - timedelta(days=1)),
]

for label, requires_admin, move_date in tests:
    result = gate.check(
        requires_admin_forward=requires_admin,
        move_in_date=move_date,
    )

    print("\nTEST:", label)
    print(result.model_dump())