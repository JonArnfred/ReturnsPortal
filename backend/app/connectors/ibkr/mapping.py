"""Pure mapping from Flex rows to domain records. No I/O; unit-tested against recorded rows.

Conventions established from real statements (2026-09-21):
- ``Trades`` at execution level: ``quantity`` is signed (bought positive), ``proceeds`` is the cash
  effect in the instrument currency before commission (buy negative), ``ibCommission`` is a
  separate amount in ``ibCommissionCurrency``. A trade becomes a ``trade`` row plus a
  ``commission`` row linked by ``related_ref``, so the two together equal ``netCash``.
- Currency conversions are trades with ``assetCategory = CASH`` and a pair symbol such as
  ``EUR.ILS``: ``quantity`` is the amount of the first currency, ``proceeds`` the amount of the
  second (``currency``). They become two ``transfer`` legs, one per currency, like Saxo's
  internal transfers, so the engine books the spread as a conversion cost.
- ``CashTransactions`` ``type`` names the kind. Deposits and withdrawals share one type
  (``Deposits/Withdrawals``) and are told apart by sign. Rows are booked on ``reportDate``, when
  IBKR's own NAV reflects them; a dividend's ``dateTime`` is the pay date and can precede that by
  days. Dividends and withholding tax carry the security.
- IBKR has one account with a balance per currency, so each row's account currency is the row
  currency and the account amount is the local amount. Base amounts are in the app's reporting
  currency: ``fxRateToBase`` (base per one unit of the row currency, the app's convention too) is
  used when the broker's own base is the reporting currency, otherwise the ECB rate of the day
  (``BaseConversion``).
- ``TradeExecutionTime`` is what the position rebuild orders same-day trades by; Flex rows get an
  ISO ``executed_at`` in ``raw`` for the same purpose.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.connectors.ibkr.dto import (
    FlexAccountInformation,
    FlexCashReportCurrency,
    FlexCashTransaction,
    FlexConversionRate,
    FlexCorporateAction,
    FlexEquitySummary,
    FlexOpenPosition,
    FlexPriorPeriodPosition,
    FlexSecurityInfo,
    FlexTrade,
    FlexTransfer,
)
from app.domain.models import (
    BrokerFxRate,
    CashSnapshotRow,
    LedgerKind,
    LedgerRow,
    PositionSnapshotRow,
    SecurityKey,
    SecurityRecord,
)
from app.services.connection_service import BrokerAccount

BROKER = "ibkr"
STATEMENT_ENDPOINT = "flex/statement/"
CASH_ASSET = "CASH"
CANCELLED_CODE = "Ca"

# IBKR listing exchange codes to ISO MICs, for the ``ticker:MIC`` key and the Yahoo fallback.
EXCHANGE_MIC: dict[str, str] = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "ARCA": "ARCX",
    "AMEX": "XASE",
    "BATS": "BATS",
    "LSE": "XLON",
    "LSEETF": "XLON",
    "IBIS": "XETR",
    "IBIS2": "XETR",
    "FWB": "XFRA",
    "FWB2": "XFRA",
    "SWB": "XSTU",
    "SBF": "XPAR",
    "AEB": "XAMS",
    "ENEXT.BE": "XBRU",
    "BVL": "XLIS",
    "BM": "XMAD",
    "BVME": "XMIL",
    "BVME.ETF": "XMIL",
    "EBS": "XSWX",
    "VSE": "XWBO",
    "WSE": "XWAR",
    "CPH": "XCSE",
    "SFB": "XSTO",
    "HEX": "XHEL",
    "OSE": "XOSL",
    "TSE": "XTSE",
    "TSEJ": "XTKS",
    "ASX": "XASX",
    "SEHK": "XHKG",
    "SGX": "XSES",
    "NZX": "XNZE",
    "TASE": "XTAE",
}

CASH_KINDS: dict[str, LedgerKind] = {
    "Dividends": "dividend",
    "Payment In Lieu Of Dividends": "dividend",
    "Withholding Tax": "withholding_tax",
    "Broker Interest Paid": "interest",
    "Broker Interest Received": "interest",
    "Bond Interest Received": "interest",
    "Bond Interest Paid": "interest",
    "Other Fees": "fee",
    "Advisor Fees": "fee",
    "Commission Adjustments": "commission",
}
# Live statements say "Deposits/Withdrawals"; the ibflex client documents the ampersand spelling.
DEPOSIT_WITHDRAWAL_TYPES = frozenset({"Deposits/Withdrawals", "Deposits & Withdrawals"})

# Fields of Account Information worth keeping in raw payloads; the rest is personal data
# (address, date of birth, email) that the app has no use for.
ACCOUNT_INFORMATION_FIELDS = frozenset(
    {
        "accountId",
        "acctAlias",
        "model",
        "currency",
        "name",
        "accountType",
        "customerType",
        "accountCapabilities",
        "dateOpened",
        "dateFunded",
        "dateClosed",
        "ibEntity",
        "masterName",
        "taxLotMatchingMethod",
    }
)

FxLookup = Callable[[str, date], Decimal | None]


@dataclass(frozen=True)
class BaseConversion:
    """How a row's amounts become base amounts. ``base_currency`` is the app's reporting currency,
    ``broker_base`` the currency IBKR's ``fxRateToBase`` converts into, ``fx`` the forward-filled
    ECB lookup (reporting currency per one unit of a currency on a day)."""

    base_currency: str
    broker_base: str
    fx: FxLookup

    def rate(
        self, currency: str, day: date, *, row_currency: str | None = None, row_rate: Decimal | None = None
    ) -> Decimal | None:
        if currency == self.base_currency:
            return Decimal(1)
        if self.broker_base == self.base_currency and currency == row_currency and row_rate is not None:
            return row_rate
        return self.fx(currency, day)


def security_key(conid: int, asset_category: str) -> SecurityKey:
    return SecurityKey(broker=BROKER, uic=conid, asset_type=asset_category)


def mic_for(listing_exchange: str | None) -> str | None:
    return EXCHANGE_MIC.get((listing_exchange or "").upper()) if listing_exchange else None


def codes(value: str | None) -> frozenset[str]:
    """``"O;P"`` -> ``{"O", "P"}``."""
    return frozenset(part.strip() for part in (value or "").split(";") if part.strip())


def strip_account_information(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if key in ACCOUNT_INFORMATION_FIELDS}


def map_account(info: FlexAccountInformation, raw: dict[str, Any]) -> BrokerAccount:
    return BrokerAccount(
        account_key=info.account_id,
        account_id=info.account_id,
        currency=info.currency,
        account_type=info.account_type,
        active=True,
        raw=strip_account_information(raw),
    )


def map_security(info: FlexSecurityInfo, raw: dict[str, Any]) -> SecurityRecord:
    symbol = info.symbol or str(info.conid)
    return SecurityRecord(
        key=security_key(info.conid, info.asset_category or "STK"),
        symbol=symbol,
        ticker=symbol,
        mic=mic_for(info.listing_exchange),
        name=info.description,
        currency=info.currency,
        exchange_id=info.listing_exchange,
        isin=info.isin,
        raw=raw,
    )


def security_from_row(
    *,
    conid: int,
    asset_category: str,
    symbol: str | None,
    description: str | None,
    currency: str | None,
    listing_exchange: str | None,
    isin: str | None,
    raw: dict[str, Any],
    source: str,
) -> SecurityRecord:
    """Fallback security record from a trade, position or cash row when the instrument information
    section did not list the instrument."""
    return SecurityRecord(
        key=security_key(conid, asset_category),
        symbol=symbol or str(conid),
        ticker=symbol or str(conid),
        mic=mic_for(listing_exchange),
        name=description,
        currency=currency,
        exchange_id=listing_exchange,
        isin=isin,
        raw={"source": source, "row": raw},
    )


def _base_amount(amount: Decimal, rate: Decimal | None) -> Decimal | None:
    return None if rate is None else amount * rate


def _executed_raw(raw: dict[str, Any], executed: datetime | None) -> dict[str, Any]:
    return {**raw, "executed_at": executed.isoformat() if executed else None}


def is_cancelled(trade: FlexTrade) -> bool:
    return CANCELLED_CODE in codes(trade.notes)


def map_trade(trade: FlexTrade, raw: dict[str, Any], *, conversion: BaseConversion) -> list[LedgerRow]:
    """Ledger rows for one execution: the trade (or the two legs of a currency conversion) and its
    commission. Cancelled executions and zero-quantity rows give nothing."""
    if is_cancelled(trade) or trade.quantity == 0 or trade.trade_date is None:
        return []
    day = trade.trade_date
    rows: list[LedgerRow] = []
    common = {
        "trade_date": day,
        "value_date": trade.settle_date_target,
        "account_key": trade.account_id,
        "base_currency": conversion.base_currency,
        "source_endpoint": f"{STATEMENT_ENDPOINT}Trades",
        "raw": _executed_raw(raw, trade.date_time),
    }
    if trade.asset_category == CASH_ASSET:
        first, _, _second = (trade.symbol or "").partition(".")
        rows.extend(_conversion_legs(trade, first or trade.currency, common, conversion=conversion))
    else:
        proceeds = trade.proceeds if trade.proceeds is not None else Decimal(0)
        rate = conversion.rate(trade.currency, day, row_currency=trade.currency, row_rate=trade.fx_rate_to_base)
        rows.append(
            LedgerRow(
                broker_ref=f"trade:{trade.trade_id}",
                kind="trade",
                security=security_key(trade.conid, trade.asset_category),
                quantity=trade.quantity,
                price=trade.trade_price,
                currency=trade.currency,
                amount_local=proceeds,
                account_currency=trade.currency,
                amount_account=proceeds,
                amount_base=_base_amount(proceeds, rate),
                fx_rate_base=rate,
                related_ref=None,
                description=trade.description or trade.symbol,
                **common,
            )
        )
    if trade.ib_commission and trade.ib_commission != 0:
        currency = trade.ib_commission_currency or trade.currency
        rate = conversion.rate(currency, day, row_currency=trade.currency, row_rate=trade.fx_rate_to_base)
        rows.append(
            LedgerRow(
                broker_ref=f"commission:{trade.trade_id}",
                kind="commission",
                security=None
                if trade.asset_category == CASH_ASSET
                else security_key(trade.conid, trade.asset_category),
                quantity=None,
                price=None,
                currency=currency,
                amount_local=trade.ib_commission,
                account_currency=currency,
                amount_account=trade.ib_commission,
                amount_base=_base_amount(trade.ib_commission, rate),
                fx_rate_base=rate,
                related_ref=f"trade:{trade.trade_id}",
                description=f"Commission {trade.symbol or ''}".strip(),
                **common,
            )
        )
    return rows


def _conversion_legs(
    trade: FlexTrade, first_currency: str, common: dict[str, Any], *, conversion: BaseConversion
) -> list[LedgerRow]:
    """``SELL -1000 EUR.ILS`` at 3.4896 -> ``-1000 EUR`` and ``+3489.6 ILS``."""
    assert trade.trade_date is not None
    legs = [
        (first_currency, trade.quantity),
        (trade.currency, trade.proceeds if trade.proceeds is not None else Decimal(0)),
    ]
    rows = []
    for currency, amount in legs:
        rate = conversion.rate(currency, trade.trade_date, row_currency=trade.currency, row_rate=trade.fx_rate_to_base)
        other = legs[1][0] if currency == first_currency else first_currency
        rows.append(
            LedgerRow(
                broker_ref=f"fx:{trade.trade_id}:{currency}",
                kind="transfer",
                security=None,
                quantity=None,
                price=trade.trade_price,
                currency=currency,
                amount_local=amount,
                account_currency=currency,
                amount_account=amount,
                amount_base=_base_amount(amount, rate),
                fx_rate_base=rate,
                related_ref=f"fx:{trade.trade_id}:{other}",
                description=f"FX {trade.symbol} @ {trade.trade_price}",
                **common,
            )
        )
    return rows


def cash_kind(row: FlexCashTransaction) -> LedgerKind:
    if row.type in DEPOSIT_WITHDRAWAL_TYPES:
        return "deposit" if row.amount >= 0 else "withdrawal"
    return CASH_KINDS.get(row.type, "other")


def map_cash_transaction(
    row: FlexCashTransaction, raw: dict[str, Any], *, conversion: BaseConversion
) -> LedgerRow | None:
    """Booked on ``reportDate``, the day the movement enters IBKR's statement and NAV; a dividend's
    ``dateTime`` is its pay date, which can be days earlier."""
    day = row.report_date or (row.date_time.date() if row.date_time else None) or row.settle_date
    if day is None:
        return None
    has_security = row.conid is not None and row.asset_category not in (None, CASH_ASSET)
    rate = conversion.rate(row.currency, day, row_currency=row.currency, row_rate=row.fx_rate_to_base)
    return LedgerRow(
        broker_ref=f"cash:{row.transaction_id}",
        kind=cash_kind(row),
        trade_date=day,
        value_date=row.settle_date,
        account_key=row.account_id,
        security=security_key(row.conid, row.asset_category)
        if has_security and row.conid is not None and row.asset_category
        else None,
        quantity=None,
        price=None,
        currency=row.currency,
        amount_local=row.amount,
        account_currency=row.currency,
        amount_account=row.amount,
        base_currency=conversion.base_currency,
        amount_base=_base_amount(row.amount, rate),
        fx_rate_base=rate,
        related_ref=f"action:{row.action_id}" if row.action_id else (f"trade:{row.trade_id}" if row.trade_id else None),
        description=row.description or row.type,
        source_endpoint=f"{STATEMENT_ENDPOINT}CashTransactions",
        raw=_executed_raw(raw, row.date_time),
    )


def map_corporate_action(
    row: FlexCorporateAction, raw: dict[str, Any], *, conversion: BaseConversion
) -> LedgerRow | None:
    """A corporate action leg: quantity change on the security with whatever cash it carried."""
    day = (row.date_time.date() if row.date_time else None) or row.report_date
    if day is None or row.conid is None or not row.asset_category:
        return None
    currency = row.currency or conversion.base_currency
    cash = row.proceeds if row.proceeds is not None else Decimal(0)
    rate = conversion.rate(currency, day, row_currency=currency, row_rate=row.fx_rate_to_base)
    ref = row.transaction_id or f"{row.action_id}:{row.conid}:{day.isoformat()}"
    return LedgerRow(
        broker_ref=f"corp:{ref}",
        kind="corporate_action",
        trade_date=day,
        value_date=row.report_date,
        account_key=row.account_id,
        security=security_key(row.conid, row.asset_category),
        quantity=row.quantity,
        price=None,
        currency=currency,
        amount_local=cash,
        account_currency=currency,
        amount_account=cash,
        base_currency=conversion.base_currency,
        amount_base=_base_amount(cash, rate),
        fx_rate_base=rate,
        related_ref=f"action:{row.action_id}" if row.action_id else None,
        description=row.action_description or row.description,
        source_endpoint=f"{STATEMENT_ENDPOINT}CorporateActions",
        raw=_executed_raw(raw, row.date_time),
    )


def map_transfer(row: FlexTransfer, raw: dict[str, Any], *, conversion: BaseConversion) -> LedgerRow | None:
    """A position or cash transfer in or out of the account, recorded as a ``transfer``. A position
    transfer is recorded with its quantity but the engine does not open a position from it yet."""
    day = row.date or (row.date_time.date() if row.date_time else None) or row.report_date
    if day is None:
        return None
    currency = row.currency or conversion.base_currency
    is_cash = row.asset_category in (None, CASH_ASSET) or row.conid is None
    amount = row.cash_transfer if is_cash and row.cash_transfer is not None else Decimal(0)
    rate = conversion.rate(currency, day, row_currency=currency, row_rate=row.fx_rate_to_base)
    ref = row.transaction_id or f"{row.type}:{row.direction}:{row.conid or currency}:{day.isoformat()}"
    return LedgerRow(
        broker_ref=f"transfer:{ref}",
        kind="transfer",
        trade_date=day,
        value_date=row.report_date,
        account_key=row.account_id,
        security=None if is_cash else security_key(row.conid, row.asset_category or "STK"),  # type: ignore[arg-type]
        quantity=None if is_cash else row.quantity,
        price=row.transfer_price,
        currency=currency,
        amount_local=amount,
        account_currency=currency,
        amount_account=amount,
        base_currency=conversion.base_currency,
        amount_base=_base_amount(amount, rate),
        fx_rate_base=rate,
        related_ref=None,
        description=f"{row.type or 'Transfer'} {row.direction or ''} {row.description or ''}".strip(),
        source_endpoint=f"{STATEMENT_ENDPOINT}Transfers",
        raw=_executed_raw(raw, row.date_time),
    )


def map_open_position(
    row: FlexOpenPosition,
    raw: dict[str, Any],
    *,
    snapshot_date: date,
    fetched_at: datetime,
    conversion: BaseConversion,
) -> PositionSnapshotRow:
    day = row.report_date or snapshot_date
    currency = row.currency or conversion.broker_base
    rate = conversion.rate(currency, day, row_currency=currency, row_rate=row.fx_rate_to_base)
    value = row.position_value
    return PositionSnapshotRow(
        snapshot_date=day,
        account_key=row.account_id,
        broker_position_id=f"{row.account_id or ''}:{row.conid}",
        security=security_key(row.conid, row.asset_category),
        quantity=row.position,
        open_price=row.open_price,
        current_price=row.mark_price,
        currency=row.currency,
        market_value_local=value,
        market_value_base=_base_amount(value, rate) if value is not None else None,
        fx_rate_base=rate,
        raw=raw,
        fetched_at=fetched_at,
    )


@dataclass(frozen=True)
class PriceMark:
    """IBKR's closing mark of a security on one day, in the instrument currency."""

    security: SecurityKey
    day: date
    price: Decimal
    currency: str | None


def map_prior_period_position(row: FlexPriorPeriodPosition) -> PriceMark | None:
    """The day's mark of a held security; cash rows and rows without a date or price give None."""
    if row.asset_category == CASH_ASSET or row.date is None or row.price is None or row.price <= 0:
        return None
    return PriceMark(security_key(row.conid, row.asset_category), row.date, row.price, row.currency)


def trade_mark(trade: FlexTrade) -> PriceMark | None:
    """IBKR's close of the trade date (``closePrice``); it covers the day a position is opened,
    which Prior Period Positions (positions held at the previous close) does not."""
    if (
        trade.asset_category == CASH_ASSET
        or is_cancelled(trade)
        or trade.trade_date is None
        or trade.close_price is None
        or trade.close_price <= 0
    ):
        return None
    return PriceMark(
        security_key(trade.conid, trade.asset_category), trade.trade_date, trade.close_price, trade.currency
    )


def open_position_mark(row: FlexOpenPosition, *, snapshot_date: date) -> PriceMark | None:
    """The mark of an open position on the statement's report date."""
    if row.asset_category == CASH_ASSET or row.mark_price is None or row.mark_price <= 0:
        return None
    return PriceMark(
        security_key(row.conid, row.asset_category), row.report_date or snapshot_date, row.mark_price, row.currency
    )


def map_conversion_rates(
    rows: list[FlexConversionRate], *, conversion: BaseConversion, currencies: set[str]
) -> list[BrokerFxRate]:
    """IBKR's rates of the held ``currencies`` into the reporting currency. IBKR converts into its
    account base; the base is crossed into the reporting currency with the rate ``map_nav`` uses for
    the account value, so the two compare like with like. The base itself is included each day."""
    rates: dict[tuple[date, str], BrokerFxRate] = {}
    for row in rows:
        if row.report_date is None or row.to_currency != conversion.broker_base or row.rate <= 0:
            continue
        base_rate = conversion.rate(conversion.broker_base, row.report_date)
        if base_rate is None:
            continue
        base = conversion.broker_base
        if base in currencies:
            rates[(row.report_date, base)] = BrokerFxRate(
                day=row.report_date, currency=base, rate=base_rate, quote_currency=base, quote_rate=Decimal(1)
            )
        if row.from_currency in currencies and row.from_currency != base:
            rates[(row.report_date, row.from_currency)] = BrokerFxRate(
                day=row.report_date,
                currency=row.from_currency,
                rate=row.rate * base_rate,
                quote_currency=base,
                quote_rate=row.rate,
            )
    return list(rates.values())


def map_cash_report(
    row: FlexCashReportCurrency, raw: dict[str, Any], *, snapshot_date: date, fetched_at: datetime
) -> CashSnapshotRow | None:
    """Ending cash of one currency, keyed on the account; the base summary row is skipped."""
    if row.currency == "BASE_SUMMARY" or row.ending_cash is None:
        return None
    return CashSnapshotRow(
        snapshot_date=row.to_date or snapshot_date,
        account_key=row.account_id or "",
        currency=row.currency,
        cash_balance=row.ending_cash,
        total_value=None,
        raw=raw,
        fetched_at=fetched_at,
    )


def map_nav(
    row: FlexEquitySummary,
    raw: dict[str, Any],
    *,
    snapshot_date: date,
    fetched_at: datetime,
    conversion: BaseConversion,
) -> CashSnapshotRow | None:
    """Account value per report day in the reporting currency, on the empty account key the engine
    reads ``broker_value`` from. Accrued dividends and interest are taken out because the ledger
    books them when they are paid. None when the day's rate into the reporting currency is unknown."""
    day = row.report_date or snapshot_date
    rate = conversion.rate(row.currency, day)
    if rate is None:
        return None
    accruals = (row.dividend_accruals or Decimal(0)) + (row.interest_accruals or Decimal(0))
    return CashSnapshotRow(
        snapshot_date=day,
        account_key="",
        currency=conversion.base_currency,
        cash_balance=(row.cash if row.cash is not None else Decimal(0)) * rate,
        total_value=(row.total - accruals) * rate,
        raw=raw,
        fetched_at=fetched_at,
    )
