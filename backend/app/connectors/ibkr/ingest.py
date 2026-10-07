"""Map captured Flex statements into securities, ledger rows and snapshots, then reconcile.

Reads only from ``broker_raw_payloads``; never calls IBKR. Safe to rerun: every write is an
upsert keyed on IBKR's own identifiers, and rows repeated across overlapping pulls collapse on
those identifiers (the latest capture wins).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date
from decimal import Decimal
from typing import Any

import app.services.connection_service as connections
from app.connectors.ibkr import mapping
from app.connectors.ibkr.dto import (
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
from app.domain.models import CashSnapshotRow, DailyBar, LedgerRow, PositionSnapshotRow, SecurityKey, SecurityRecord
from app.services import fx_service, position_service, price_service, settings_service
from app.services import ledger_service as ledger
from app.services.snapshot_reconcile import reconcile

logger = logging.getLogger("returns-portal.ibkr")


@dataclass
class IngestReport:
    connection_id: int
    portfolio_id: int = 0
    securities: int = 0
    trades: int = 0
    cash_transactions: int = 0
    corporate_actions: int = 0
    transfers: int = 0
    ledger_rows: int = 0
    positions_rebuilt: int = 0
    positions: int = 0
    cash_rows: int = 0
    nav_days: int = 0
    fx_rates: int = 0
    price_marks: int = 0
    warnings: list[str] = field(default_factory=list)
    reconciliation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__


SectionRow = tuple[dict[str, Any], dict[str, Any], connections.RawPayload]


def _rows(connection_id: int, section: str, *, latest_run_only: bool) -> list[SectionRow]:
    """(row, statement attributes, payload) for every row of a section, oldest capture first."""
    out: list[SectionRow] = []
    for payload in connections.raw_payloads(
        connection_id, f"{mapping.STATEMENT_ENDPOINT}{section}", latest_run_only=latest_run_only
    ):
        body = payload.payload
        if not isinstance(body, dict):
            continue
        statement = body.get("statement") or {}
        for row in body.get("rows") or []:
            if isinstance(row, dict):
                out.append((row, statement, payload))
    return out


def _latest_by(rows: list[SectionRow], key: str) -> list[SectionRow]:
    """Collapse repeats of the same identifier; the latest capture wins."""
    by_id: dict[str, SectionRow] = {}
    for item in rows:
        identifier = str(item[0].get(key) or "")
        if identifier:
            by_id[identifier] = item
    return list(by_id.values())


def _fx_lookup(base_currency: str, report: IngestReport) -> mapping.FxLookup:
    """Forward-filled ECB rate into the reporting currency; each missing (currency, day) is warned once."""
    missing: set[tuple[str, date]] = set()

    def lookup(currency: str, day: date) -> Decimal | None:
        rate = fx_service.rate_on(base_currency, currency, day)
        if rate is None and (currency, day) not in missing:
            missing.add((currency, day))
            report.warnings.append(f"no {currency} rate on {day}; base amount left empty")
        return rate

    return lookup


def ingest(connection_id: int) -> IngestReport:
    report = IngestReport(connection_id=connection_id)
    connection = connections.get_connection(connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id} does not exist")
    if not connection.base_currency:
        raise RuntimeError("the connection has no base currency yet; run a sync first")
    # The portfolio is booked in the user's reporting currency; the broker's own base only decides
    # whether IBKR's fxRateToBase can be used as is.
    base_currency = settings_service.reporting_currency()
    report.portfolio_id = ledger.upsert_portfolio(
        connection_id,
        name=f"IBKR {connection.client_name or connection.client_key or ''}".strip(),
        base_currency=base_currency,
    )
    conversion = mapping.BaseConversion(
        base_currency=base_currency, broker_base=connection.base_currency, fx=_fx_lookup(base_currency, report)
    )

    # Reference data first: the instrument section, then whatever held or traded instruments it lacks.
    securities: dict[SecurityKey, SecurityRecord] = {}
    for row, _, _ in _latest_by(_rows(connection_id, "SecuritiesInfo", latest_run_only=False), "conid"):
        record = mapping.map_security(FlexSecurityInfo.model_validate(row), row)
        securities[record.key] = record

    trades = [
        (FlexTrade.model_validate(row), row)
        for row, _, _ in _latest_by(_rows(connection_id, "Trades", latest_run_only=False), "tradeID")
    ]
    cash_transactions = [
        (FlexCashTransaction.model_validate(row), row)
        for row, _, _ in _latest_by(_rows(connection_id, "CashTransactions", latest_run_only=False), "transactionID")
    ]
    corporate_actions = [
        (FlexCorporateAction.model_validate(row), row)
        for row, _, _ in _rows(connection_id, "CorporateActions", latest_run_only=False)
    ]
    transfers = [
        (FlexTransfer.model_validate(row), row)
        for row, _, _ in _rows(connection_id, "Transfers", latest_run_only=False)
    ]
    position_rows = [
        (FlexOpenPosition.model_validate(row), row, statement, payload)
        for row, statement, payload in _rows(connection_id, "OpenPositions", latest_run_only=True)
    ]

    def ensure_security(*, conid: int | None, asset_category: str | None, row: dict[str, Any], source: str) -> None:
        if conid is None or not asset_category or asset_category == mapping.CASH_ASSET:
            return
        key = mapping.security_key(conid, asset_category)
        if key in securities:
            return
        securities[key] = mapping.security_from_row(
            conid=conid,
            asset_category=asset_category,
            symbol=row.get("symbol"),
            description=row.get("description"),
            currency=row.get("currency"),
            listing_exchange=row.get("listingExchange"),
            isin=row.get("isin"),
            raw=row,
            source=source,
        )
        report.warnings.append(f"no instrument information for conid {conid}; derived from a {source} row")

    for trade, row in trades:
        ensure_security(conid=trade.conid, asset_category=trade.asset_category, row=row, source="trade")
    for position, row, _, _ in position_rows:
        ensure_security(conid=position.conid, asset_category=position.asset_category, row=row, source="position")
    for cash, row in cash_transactions:
        ensure_security(conid=cash.conid, asset_category=cash.asset_category, row=row, source="cash")
    for action, row in corporate_actions:
        ensure_security(conid=action.conid, asset_category=action.asset_category, row=row, source="corporate action")
    for transfer, row in transfers:
        ensure_security(conid=transfer.conid, asset_category=transfer.asset_category, row=row, source="transfer")
    report.securities = ledger.upsert_securities(list(securities.values()))
    ids = ledger.security_ids(mapping.BROKER)

    rows: list[LedgerRow] = []
    for trade, row in trades:
        mapped = mapping.map_trade(trade, row, conversion=conversion)
        report.trades += 1 if mapped else 0
        rows.extend(mapped)
    for cash, row in cash_transactions:
        mapped_row = mapping.map_cash_transaction(cash, row, conversion=conversion)
        if mapped_row is not None:
            rows.append(mapped_row)
            report.cash_transactions += 1
    for action, row in corporate_actions:
        mapped_row = mapping.map_corporate_action(action, row, conversion=conversion)
        if mapped_row is not None:
            rows.append(mapped_row)
            report.corporate_actions += 1
    for transfer, row in transfers:
        mapped_row = mapping.map_transfer(transfer, row, conversion=conversion)
        if mapped_row is not None:
            rows.append(mapped_row)
            report.transfers += 1
            if mapped_row.security is not None:
                report.warnings.append(
                    f"position transfer {mapped_row.broker_ref} recorded; "
                    "the engine does not open positions from transfers"
                )
    for index, ledger_row in enumerate(rows):
        if ledger_row.security is not None and ledger_row.security not in ids:
            report.warnings.append(f"{ledger_row.broker_ref} references unknown security {ledger_row.security.uic}")
            rows[index] = ledger_row.model_copy(update={"security": None})
    report.ledger_rows = ledger.upsert_ledger(connection_id, report.portfolio_id, rows, ids)
    report.positions_rebuilt = int(position_service.rebuild(report.portfolio_id).get("position_rows", 0))

    snapshots: list[PositionSnapshotRow] = []
    for position, row, statement, payload in position_rows:
        snapshot_date = date.fromisoformat(statement["toDate"])
        snapshots.append(
            mapping.map_open_position(
                position,
                row,
                snapshot_date=snapshot_date,
                fetched_at=payload.fetched_at.astimezone(UTC),
                conversion=conversion,
            )
        )
    report.positions = ledger.upsert_position_snapshots(connection_id, report.portfolio_id, snapshots, ids)

    cash_rows: list[CashSnapshotRow] = []
    for row, statement, payload in _rows(connection_id, "CashReport", latest_run_only=True):
        mapped_cash = mapping.map_cash_report(
            FlexCashReportCurrency.model_validate(row),
            row,
            snapshot_date=date.fromisoformat(statement["toDate"]),
            fetched_at=payload.fetched_at.astimezone(UTC),
        )
        if mapped_cash is not None:
            cash_rows.append(mapped_cash)
    report.cash_rows = ledger.upsert_cash_snapshots(connection_id, report.portfolio_id, cash_rows)

    nav_rows: dict[date, CashSnapshotRow] = {}
    for row, statement, payload in _rows(connection_id, "EquitySummaryInBase", latest_run_only=False):
        nav = mapping.map_nav(
            FlexEquitySummary.model_validate(row),
            row,
            snapshot_date=date.fromisoformat(statement["toDate"]),
            fetched_at=payload.fetched_at.astimezone(UTC),
            conversion=conversion,
        )
        if nav is not None:
            nav_rows[nav.snapshot_date] = nav
    report.nav_days = ledger.upsert_cash_snapshots(connection_id, report.portfolio_id, list(nav_rows.values()))

    # IBKR's own FX rates for the currencies the account uses, so the engine can tell how much of a
    # NAV difference is ECB vs IBKR FX.
    currencies = {row.currency for row in rows} | {row.account_currency for row in rows if row.account_currency}
    fx_rates = mapping.map_conversion_rates(
        [
            FlexConversionRate.model_validate(row)
            for row, _, _ in _rows(connection_id, "ConversionRates", latest_run_only=False)
        ],
        conversion=conversion,
        currencies=currencies,
    )
    report.fx_rates = fx_service.upsert_broker_rates(report.portfolio_id, fx_rates)

    # IBKR's daily marks become the closes of the securities it holds, so the engine values them
    # the way IBKR's NAV does (a Xetra close and IBKR's later mark differ by percents on a
    # leveraged product). Prior Period Positions covers the days a position was held at the previous
    # close; a trade's closePrice covers the day it was opened, and the open-position mark the
    # statement's last day. They agree where they overlap; the latest capture of a (security, day) wins.
    marks: dict[tuple[SecurityKey, date], mapping.PriceMark] = {}
    for trade, _ in trades:
        mark = mapping.trade_mark(trade)
        if mark is not None:
            marks[(mark.security, mark.day)] = mark
    for row, statement, _ in _rows(connection_id, "OpenPositions", latest_run_only=False):
        mark = mapping.open_position_mark(
            FlexOpenPosition.model_validate(row), snapshot_date=date.fromisoformat(statement["toDate"])
        )
        if mark is not None:
            marks[(mark.security, mark.day)] = mark
    for row, _, _ in _rows(connection_id, "PriorPeriodPositions", latest_run_only=False):
        mark = mapping.map_prior_period_position(FlexPriorPeriodPosition.model_validate(row))
        if mark is not None:
            marks[(mark.security, mark.day)] = mark
    bars = [
        DailyBar(
            security_id=ids[mark.security],
            price_date=mark.day,
            open=None,
            high=None,
            low=None,
            close=mark.price,
            volume=None,
            currency=mark.currency,
            source="ibkr",
        )
        for mark in marks.values()
        if mark.security in ids
    ]
    report.price_marks = price_service.upsert_broker_marks(bars)

    report.reconciliation = reconcile(connection_id)
    return report
