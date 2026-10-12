"""The Budget tab: monthly budgets against your spending and your state's."""

from fastapi import APIRouter, HTTPException, Query

from models.schemas import BudgetSettings
from services import benchmarks, budgeting

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("/overview")
def overview(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$")):
    return budgeting.overview(month)


@router.get("/settings")
def get_settings():
    return {**benchmarks.settings(), "areas": benchmarks.areas(),
            "source": benchmarks.metadata()}


@router.put("/settings")
def put_settings(body: BudgetSettings):
    try:
        return benchmarks.save_settings(body.state, body.household_size)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/fill-from-state")
def fill_from_state():
    """Fill empty budgets with the state average. Never overwrites one you set."""
    return budgeting.fill_from_state()
