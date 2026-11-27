"""Fiduciary money tables (ERP/MGA integrity U2).

These tables are the durable home for stores that previously lived only in
``phins_ledger_data.json`` / the ledger snapshot artifact:

* ``health_wallets`` — customer health-wallet dicts (``HEALTH_WALLETS``)
* ``wallet_withdrawals`` — withdrawal request lifecycle (``WALLET_WITHDRAWALS``)
* ``nft_ledger_entries`` — sealed NFT mint/transfer rows (``NFT_LEDGER``)
* ``investment_accounts`` — landed savings AUM (``INVESTMENT_ACCOUNTS``)
* ``balance_sheet_counters`` — PHINS balance-sheet singleton (``PHINS_BALANCE_SHEET``)

Each row carries canonical JSON + sha256. A checksum mismatch withholds the
row on read and never overwrites it with a fresh payload. Marketplace
``wallet_accounts`` / ``wallet_holds`` stay the supply-chain payment rail;
these tables own the customer fiduciary books.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from database.models import Base


class HealthWallet(Base):
    """One sealed health-wallet record per customer."""

    __tablename__ = 'health_wallets'

    id = Column(String(80), primary_key=True)  # customer_id
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True
    )


class WalletWithdrawal(Base):
    """One sealed wallet-withdrawal request."""

    __tablename__ = 'wallet_withdrawals'

    id = Column(String(120), primary_key=True)  # withdrawal_id
    customer_id = Column(String(80), nullable=True, index=True)
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True
    )


class NftLedgerEntry(Base):
    """One sealed NFT ledger token row."""

    __tablename__ = 'nft_ledger_entries'

    id = Column(String(120), primary_key=True)  # token_id
    customer_id = Column(String(80), nullable=True, index=True)
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True
    )


class InvestmentAccount(Base):
    """One sealed investment/savings account per customer."""

    __tablename__ = 'investment_accounts'

    id = Column(String(80), primary_key=True)  # customer_id
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True
    )


class BalanceSheetCounters(Base):
    """Singleton (or named) sealed balance-sheet counter block."""

    __tablename__ = 'balance_sheet_counters'

    id = Column(String(80), primary_key=True)  # e.g. 'phins'
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True
    )


FIDUCIARY_MODELS = (
    HealthWallet,
    WalletWithdrawal,
    NftLedgerEntry,
    InvestmentAccount,
    BalanceSheetCounters,
)

__all__ = [
    'HealthWallet',
    'WalletWithdrawal',
    'NftLedgerEntry',
    'InvestmentAccount',
    'BalanceSheetCounters',
    'FIDUCIARY_MODELS',
]
