"""Typed views of an Activity Flex statement. Rows are XML attribute maps; values arrive as strings.

``parse_statements`` turns the report XML into one ``FlexStatementData`` per account with every
section as a list of attribute dictionaries. The pydantic models below validate the rows the
mapping needs; unknown attributes are ignored, empty strings become None.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).split(";")[0].split(" ")[0]
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return date.fromisoformat(text)


def _to_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace(";", " ").strip()
    day, _, clock = text.partition(" ")
    parsed_day = _to_date(day)
    assert parsed_day is not None
    if not clock:
        return datetime.combine(parsed_day, datetime.min.time())
    if len(clock) == 6 and clock.isdigit():
        clock = f"{clock[:2]}:{clock[2:4]}:{clock[4:]}"
    return datetime.combine(parsed_day, datetime.fromisoformat(f"1970-01-01T{clock}").time())


FlexDate = Annotated[date | None, BeforeValidator(_to_date)]
FlexDateTime = Annotated[datetime | None, BeforeValidator(_to_datetime)]


class FlexModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return None if value == "" else value


class FlexAccountInformation(FlexModel):
    account_id: str = Field(alias="accountId")
    currency: str | None = None
    name: str | None = None
    account_type: str | None = Field(default=None, alias="accountType")
    date_opened: FlexDate = Field(default=None, alias="dateOpened")
    date_funded: FlexDate = Field(default=None, alias="dateFunded")


class FlexTrade(FlexModel):
    trade_id: str = Field(alias="tradeID")
    transaction_id: str | None = Field(default=None, alias="transactionID")
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str
    fx_rate_to_base: Decimal | None = Field(default=None, alias="fxRateToBase")
    asset_category: str = Field(alias="assetCategory")
    symbol: str | None = None
    description: str | None = None
    conid: int
    isin: str | None = None
    listing_exchange: str | None = Field(default=None, alias="listingExchange")
    multiplier: Decimal | None = None
    trade_date: FlexDate = Field(default=None, alias="tradeDate")
    close_price: Decimal | None = Field(default=None, alias="closePrice")
    date_time: FlexDateTime = Field(default=None, alias="dateTime")
    settle_date_target: FlexDate = Field(default=None, alias="settleDateTarget")
    quantity: Decimal
    trade_price: Decimal | None = Field(default=None, alias="tradePrice")
    proceeds: Decimal | None = None
    taxes: Decimal | None = None
    ib_commission: Decimal | None = Field(default=None, alias="ibCommission")
    ib_commission_currency: str | None = Field(default=None, alias="ibCommissionCurrency")
    net_cash: Decimal | None = Field(default=None, alias="netCash")
    buy_sell: str | None = Field(default=None, alias="buySell")
    open_close_indicator: str | None = Field(default=None, alias="openCloseIndicator")
    notes: str | None = None
    level_of_detail: str | None = Field(default=None, alias="levelOfDetail")
    ib_order_id: str | None = Field(default=None, alias="ibOrderID")
    transaction_type: str | None = Field(default=None, alias="transactionType")


class FlexCashTransaction(FlexModel):
    transaction_id: str = Field(alias="transactionID")
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str
    fx_rate_to_base: Decimal | None = Field(default=None, alias="fxRateToBase")
    asset_category: str | None = Field(default=None, alias="assetCategory")
    symbol: str | None = None
    description: str | None = None
    conid: int | None = None
    isin: str | None = None
    listing_exchange: str | None = Field(default=None, alias="listingExchange")
    date_time: FlexDateTime = Field(default=None, alias="dateTime")
    settle_date: FlexDate = Field(default=None, alias="settleDate")
    report_date: FlexDate = Field(default=None, alias="reportDate")
    ex_date: FlexDate = Field(default=None, alias="exDate")
    amount: Decimal
    type: str
    dividend_type: str | None = Field(default=None, alias="dividendType")
    trade_id: str | None = Field(default=None, alias="tradeID")
    code: str | None = None
    action_id: str | None = Field(default=None, alias="actionID")
    level_of_detail: str | None = Field(default=None, alias="levelOfDetail")


class FlexCorporateAction(FlexModel):
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str | None = None
    fx_rate_to_base: Decimal | None = Field(default=None, alias="fxRateToBase")
    asset_category: str | None = Field(default=None, alias="assetCategory")
    symbol: str | None = None
    description: str | None = None
    conid: int | None = None
    isin: str | None = None
    listing_exchange: str | None = Field(default=None, alias="listingExchange")
    report_date: FlexDate = Field(default=None, alias="reportDate")
    date_time: FlexDateTime = Field(default=None, alias="dateTime")
    action_description: str | None = Field(default=None, alias="actionDescription")
    amount: Decimal | None = None
    proceeds: Decimal | None = None
    quantity: Decimal | None = None
    type: str | None = None
    code: str | None = None
    action_id: str | None = Field(default=None, alias="actionID")
    transaction_id: str | None = Field(default=None, alias="transactionID")


class FlexTransfer(FlexModel):
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str | None = None
    fx_rate_to_base: Decimal | None = Field(default=None, alias="fxRateToBase")
    asset_category: str | None = Field(default=None, alias="assetCategory")
    symbol: str | None = None
    description: str | None = None
    conid: int | None = None
    isin: str | None = None
    listing_exchange: str | None = Field(default=None, alias="listingExchange")
    report_date: FlexDate = Field(default=None, alias="reportDate")
    date: FlexDate = None
    date_time: FlexDateTime = Field(default=None, alias="dateTime")
    type: str | None = None
    direction: str | None = None
    quantity: Decimal | None = None
    transfer_price: Decimal | None = Field(default=None, alias="transferPrice")
    position_amount: Decimal | None = Field(default=None, alias="positionAmount")
    position_amount_in_base: Decimal | None = Field(default=None, alias="positionAmountInBase")
    cash_transfer: Decimal | None = Field(default=None, alias="cashTransfer")
    transaction_id: str | None = Field(default=None, alias="transactionID")
    code: str | None = None


class FlexOpenPosition(FlexModel):
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str | None = None
    fx_rate_to_base: Decimal | None = Field(default=None, alias="fxRateToBase")
    asset_category: str = Field(alias="assetCategory")
    symbol: str | None = None
    description: str | None = None
    conid: int
    isin: str | None = None
    listing_exchange: str | None = Field(default=None, alias="listingExchange")
    multiplier: Decimal | None = None
    report_date: FlexDate = Field(default=None, alias="reportDate")
    position: Decimal
    mark_price: Decimal | None = Field(default=None, alias="markPrice")
    position_value: Decimal | None = Field(default=None, alias="positionValue")
    open_price: Decimal | None = Field(default=None, alias="openPrice")
    cost_basis_money: Decimal | None = Field(default=None, alias="costBasisMoney")
    fifo_pnl_unrealized: Decimal | None = Field(default=None, alias="fifoPnlUnrealized")
    side: str | None = None
    level_of_detail: str | None = Field(default=None, alias="levelOfDetail")


class FlexPriorPeriodPosition(FlexModel):
    """One position at one day's close (section ``PriorPeriodPositions``): IBKR's daily mark."""

    account_id: str | None = Field(default=None, alias="accountId")
    currency: str | None = None
    asset_category: str = Field(alias="assetCategory")
    symbol: str | None = None
    conid: int
    date: FlexDate = None
    price: Decimal | None = None


class FlexCashReportCurrency(FlexModel):
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str
    level_of_detail: str | None = Field(default=None, alias="levelOfDetail")
    from_date: FlexDate = Field(default=None, alias="fromDate")
    to_date: FlexDate = Field(default=None, alias="toDate")
    starting_cash: Decimal | None = Field(default=None, alias="startingCash")
    ending_cash: Decimal | None = Field(default=None, alias="endingCash")
    ending_settled_cash: Decimal | None = Field(default=None, alias="endingSettledCash")


class FlexEquitySummary(FlexModel):
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str
    report_date: FlexDate = Field(default=None, alias="reportDate")
    cash: Decimal | None = None
    stock: Decimal | None = None
    dividend_accruals: Decimal | None = Field(default=None, alias="dividendAccruals")
    interest_accruals: Decimal | None = Field(default=None, alias="interestAccruals")
    total: Decimal


class FlexConversionRate(FlexModel):
    """IBKR's rate of one currency into the account base on a report day (``ConversionRates``)."""

    report_date: FlexDate = Field(default=None, alias="reportDate")
    from_currency: str = Field(alias="fromCurrency")
    to_currency: str = Field(alias="toCurrency")
    rate: Decimal


class FlexSecurityInfo(FlexModel):
    symbol: str | None = None
    description: str | None = None
    conid: int
    currency: str | None = None
    asset_category: str | None = Field(default=None, alias="assetCategory")
    sub_category: str | None = Field(default=None, alias="subCategory")
    isin: str | None = None
    listing_exchange: str | None = Field(default=None, alias="listingExchange")
    multiplier: Decimal | None = None


@dataclass(frozen=True)
class FlexStatementData:
    """One ``FlexStatement`` element: its attributes plus every section as attribute rows."""

    account_id: str
    from_date: date
    to_date: date
    period: str
    when_generated: str
    sections: dict[str, list[dict[str, str]]]

    @property
    def attributes(self) -> dict[str, str]:
        return {
            "accountId": self.account_id,
            "fromDate": self.from_date.isoformat(),
            "toDate": self.to_date.isoformat(),
            "period": self.period,
            "whenGenerated": self.when_generated,
        }


def parse_statements(text: str) -> list[FlexStatementData]:
    """Statements of a ``FlexQueryResponse``. Raises ValueError for anything else."""
    root = ET.fromstring(text)
    if root.tag != "FlexQueryResponse":
        raise ValueError(f"expected FlexQueryResponse, got {root.tag}")
    statements: list[FlexStatementData] = []
    for statement in root.iter("FlexStatement"):
        sections: dict[str, list[dict[str, str]]] = {}
        for section in statement:
            rows = [dict(row.attrib) for row in section]
            if not rows and section.attrib:
                rows = [dict(section.attrib)]  # AccountInformation carries its fields as attributes
            sections[section.tag] = rows
        from_date = _to_date(statement.get("fromDate"))
        to_date = _to_date(statement.get("toDate"))
        if from_date is None or to_date is None:
            raise ValueError("FlexStatement without fromDate/toDate")
        statements.append(
            FlexStatementData(
                account_id=statement.get("accountId", ""),
                from_date=from_date,
                to_date=to_date,
                period=statement.get("period", ""),
                when_generated=statement.get("whenGenerated", ""),
                sections=sections,
            )
        )
    return statements
