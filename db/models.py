from dataclasses import dataclass
from typing import Optional


@dataclass
class Holding:
    id: int
    folio: str
    amc: Optional[str]
    scheme_name: str
    isin: Optional[str]
    amfi_code: Optional[str]
    rta_code: Optional[str]
    scheme_type: Optional[str]
    advisor: Optional[str]
    current_units: float
    latest_nav: Optional[float]
    latest_value: Optional[float]
    cost_value: float
    is_active: int

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], folio=row["folio"], amc=row["amc"],
            scheme_name=row["scheme_name"], isin=row["isin"],
            amfi_code=row["amfi_code"], rta_code=row["rta_code"],
            scheme_type=row["scheme_type"], advisor=row["advisor"],
            current_units=row["current_units"], latest_nav=row["latest_nav"],
            latest_value=row["latest_value"], cost_value=row["cost_value"],
            is_active=row["is_active"],
        )


@dataclass
class Transaction:
    id: int
    holding_id: Optional[int]
    folio: str
    scheme_name: str
    date: str
    description: Optional[str]
    amount: float
    units: float
    nav: Optional[float]
    balance: Optional[float]
    tx_type: Optional[str]
    dividend_rate: Optional[float]

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], holding_id=row["holding_id"], folio=row["folio"],
            scheme_name=row["scheme_name"], date=row["date"],
            description=row["description"], amount=row["amount"],
            units=row["units"], nav=row["nav"], balance=row["balance"],
            tx_type=row["tx_type"], dividend_rate=row["dividend_rate"],
        )


@dataclass
class SellDecision:
    id: int
    holding_id: Optional[int]
    scheme_name: str
    amfi_code: Optional[str]
    sell_date: str
    sell_units: float
    sell_nav: float
    sell_value: float
    reason: Optional[str]
    source: str

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], holding_id=row["holding_id"],
            scheme_name=row["scheme_name"], amfi_code=row["amfi_code"],
            sell_date=row["sell_date"], sell_units=row["sell_units"],
            sell_nav=row["sell_nav"], sell_value=row["sell_value"],
            reason=row["reason"], source=row["source"],
        )


@dataclass
class DailyPrice:
    id: int
    amfi_code: str
    scheme_name: Optional[str]
    date: str
    nav: float

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], amfi_code=row["amfi_code"],
            scheme_name=row["scheme_name"], date=row["date"], nav=row["nav"],
        )


@dataclass
class DecisionEvaluation:
    id: int
    sell_decision_id: int
    eval_date: str
    days_since_sell: int
    current_nav: float
    hypothetical_value: float
    actual_sell_value: float
    diff_pct: float
    verdict: str

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], sell_decision_id=row["sell_decision_id"],
            eval_date=row["eval_date"], days_since_sell=row["days_since_sell"],
            current_nav=row["current_nav"],
            hypothetical_value=row["hypothetical_value"],
            actual_sell_value=row["actual_sell_value"],
            diff_pct=row["diff_pct"], verdict=row["verdict"],
        )


@dataclass
class PortfolioSnapshot:
    id: int
    date: str
    total_invested: float
    total_current_value: float
    total_pnl: float
    day_change: float

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], date=row["date"],
            total_invested=row["total_invested"],
            total_current_value=row["total_current_value"],
            total_pnl=row["total_pnl"], day_change=row["day_change"],
        )
