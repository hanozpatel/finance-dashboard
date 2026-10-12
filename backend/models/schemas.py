"""Request and response models.

Only request bodies are modelled strictly. Responses are plain dicts built by
the service layer: they are wide, they change shape as tabs gain panels, and
duplicating every field here would be maintenance with no payoff for a
single-user local app.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlaidExchange(BaseModel):
    """What Plaid Link hands back to the browser on success.

    ``kind`` says which products the link token asked for, and is stored on the
    connection: an Item's products are fixed when it is created, so syncing has
    to be told rather than guess.
    """
    public_token: str = Field(min_length=1)
    institution: str | None = None
    kind: str = Field(default="bank", pattern="^(bank|investments)$")


class ManualAccount(BaseModel):
    """For accounts no aggregator can reach — Apple Savings, most notably."""
    institution: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str = Field(pattern="^(depository|credit|investment)$")
    subtype: str | None = None
    mask: str | None = None
    balance_current: float = 0.0
    credit_limit: float | None = None
    apy: float | None = None
    # Your own reference only. Never sent anywhere, and only the last four are
    # shown in listings.
    account_number: str | None = None
    notes: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    balance_current: float | None = None
    credit_limit: float | None = None
    apy: float | None = None
    is_active: bool | None = None
    subtype: str | None = None
    account_number: str | None = None
    notes: str | None = None


class TransactionUpdate(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    is_transfer: bool | None = None
    excluded: bool | None = None
    notes: str | None = None
    merchant: str | None = None


class BulkCategorize(BaseModel):
    transaction_ids: list[int] = Field(min_length=1)
    category: str = Field(min_length=1)
    subcategory: str | None = None
    # Turning a one-off fix into a standing rule is the difference between
    # tidying this month and tidying every month.
    create_rule: bool = False


class ReviewAnswer(BaseModel):
    """One answer to one merchant question in the review queue."""
    merchant_key: str = Field(min_length=1)
    category: str = Field(min_length=1)
    subcategory: str | None = None
    # On by default: without a rule the same local restaurant is a question
    # again next month.
    create_rule: bool = True
    # Set only when answering for specific rows rather than the whole merchant.
    transaction_ids: list[int] | None = None


class CategoryRule(BaseModel):
    match_type: str = Field(pattern="^(merchant_contains|description_contains|description_regex)$")
    pattern: str = Field(min_length=1)
    category: str = Field(min_length=1)
    subcategory: str | None = None
    is_transfer: bool = False
    priority: int = 100


class BudgetSettings(BaseModel):
    """Where you live and how many people the budget covers.

    Both are optional so either can be changed alone.
    """
    state: str | None = Field(default=None, min_length=2, max_length=2)
    household_size: int | None = Field(default=None, ge=1, le=10)


class BudgetUpdate(BaseModel):
    category: str = Field(min_length=1)
    monthly_limit: float = Field(ge=0)


class ManualTransaction(BaseModel):
    account_id: int
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: float
    description: str = Field(min_length=1)
    category: str | None = None
    subcategory: str | None = None
    # Recording interest on a manual savings account should move the balance
    # too, or the ledger and the headline figure drift apart.
    update_balance: bool = False


class GoalUpdate(BaseModel):
    """Every field optional — the House tab saves one slider at a time."""
    target_price: float | None = Field(default=None, gt=0)
    down_payment_pct: float | None = Field(default=None, ge=0, le=100)
    saved_amount: float | None = Field(default=None, ge=0)
    monthly_contribution: float | None = Field(default=None, ge=0)
    savings_apy: float | None = Field(default=None, ge=0, le=25)
    target_date: str | None = None
    interest_rate: float | None = Field(default=None, ge=0, le=25)
    loan_term_years: int | None = Field(default=None, ge=1, le=50)
    property_tax_rate: float | None = Field(default=None, ge=0, le=10)
    insurance_annual: float | None = Field(default=None, ge=0)
    hoa_monthly: float | None = Field(default=None, ge=0)
    pmi_rate: float | None = Field(default=None, ge=0, le=5)
    closing_cost_pct: float | None = Field(default=None, ge=0, le=10)
    gross_annual_income: float | None = Field(default=None, ge=0)
    monthly_debts: float | None = Field(default=None, ge=0)
    credit_score: int | None = Field(default=None, ge=300, le=850)
    current_rent: float | None = Field(default=None, ge=0)
    home_appreciation: float | None = Field(default=None, ge=-10, le=20)
    investment_return: float | None = Field(default=None, ge=-10, le=30)
    rent_inflation: float | None = Field(default=None, ge=-10, le=20)
    marginal_tax_rate: float | None = Field(default=None, ge=0, le=60)
    funding_account_ids: list[int] | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2)
    loan_type: str | None = Field(default=None, pattern="^(conventional|fha|va|jumbo)$")
    conforming_limit: float | None = Field(default=None, gt=0)
    va_first_use: bool | None = None


class MortgageQuote(BaseModel):
    """Standalone calculator input — independent of the saved goal."""
    home_price: float = Field(gt=0)
    down_payment_pct: float = Field(ge=0, le=100, default=20)
    interest_rate: float = Field(ge=0, le=25, default=6.5)
    loan_term_years: int = Field(ge=1, le=50, default=30)
    property_tax_rate: float = Field(ge=0, le=10, default=1.1)
    insurance_annual: float = Field(ge=0, default=1800)
    hoa_monthly: float = Field(ge=0, default=0)
    pmi_rate: float = Field(ge=0, le=5, default=0.55)
    closing_cost_pct: float = Field(ge=0, le=10, default=3)
    gross_annual_income: float = Field(ge=0, default=0)
    monthly_debts: float = Field(ge=0, default=0)
    extra_monthly: float = Field(ge=0, default=0)
    loan_type: str = Field(default="conventional", pattern="^(conventional|fha|va|jumbo)$")
    conforming_limit: float = Field(default=806_500, gt=0)
    va_first_use: bool = True


class ImportCommit(BaseModel):
    account_id: int
    mapping: dict
    # The browser sends back the file it already uploaded for preview, keyed by
    # the token the preview returned, so the file is only transferred once.
    upload_token: str
