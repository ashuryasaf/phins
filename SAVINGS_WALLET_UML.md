# PHINS Savings & Wallet Architecture - Current State

## UML Sequence Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                           PHINS SAVINGS & WALLET DATA FLOW                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────┐  ┌───────────────┐  ┌─────────────────┐  ┌────────────────┐  ┌──────────────┐  ┌───────────┐
│ Customer │  │ billing-      │  │ HEALTH_WALLETS  │  │ INVESTMENT_    │  │ ALGO_TRADING │  │ LEDGER +  │
│          │  │ settings.html │  │ (Dict)          │  │ ACCOUNTS (Dict)│  │ _BALANCES    │  │ NFT       │
└────┬─────┘  └───────┬───────┘  └────────┬────────┘  └───────┬────────┘  └──────┬───────┘  └─────┬─────┘
     │                │                   │                   │                  │                │
     │  1. Click "Add Savings"            │                   │                  │                │
     │────────────────>                   │                   │                  │                │
     │                │                   │                   │                  │                │
     │                │  2. POST /api/customer/investment/deposit               │                │
     │                │─────────────────────────────────────────>               │                │
     │                │                   │                   │                  │                │
     │                │                   │   3. Add amount   │                  │                │
     │                │                   │   + Allocate to   │                  │                │
     │                │                   │   index/bonds/    │                  │                │
     │                │                   │   crypto          │                  │                │
     │                │                   │                   │                  │                │
     │                │                   │                   │  4. Record TX    │                │
     │                │                   │                   │─────────────────────────────────>│
     │                │                   │                   │                  │                │
     │                │                   │                   │                  │   5. Generate  │
     │                │                   │                   │                  │   NFT Token    │
     │                │<──────────────────────────────────────────────────────────────────────────│
     │                │  Response: {success, account_balance, nft_token_id}     │                │
     │                │                   │                   │                  │                │
     │<───────────────│                   │                   │                  │                │
     │  UI Update: Balance shown          │                   │                  │                │
     │                │                   │                   │                  │                │
```

## Data Store Structure

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    DATA STORES (In-Memory Dictionaries)                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┐     ┌─────────────────────────────┐     ┌─────────────────────────────┐
│     HEALTH_WALLETS          │     │    INVESTMENT_ACCOUNTS      │     │   ALGO_TRADING_BALANCES     │
│  (Spendable Health Funds)   │     │    (Long-term Savings)      │     │   (Bot Trading Capital)     │
├─────────────────────────────┤     ├─────────────────────────────┤     ├─────────────────────────────┤
│ {                           │     │ {                           │     │ {                           │
│   "CUST-ASAF-001": {        │     │   "CUST-ASAF-001": {        │     │   "CUST-ASAF-001": {        │
│     balance: $16,000        │     │     balance: $9,000         │     │     available: $2,000       │
│     monthly_deposit: $382   │     │     index_balance: $3,000   │     │     in_positions: $0        │
│     transactions: [...]     │     │     bonds_balance: $1,500   │     │     total_pnl: $0           │
│   }                         │     │     crypto_balance: $500    │     │     active_bots: 0          │
│ }                           │     │     deposits: [...]         │     │     transfers: [...]        │
│                             │     │   }                         │     │   }                         │
│                             │     │ }                           │     │ }                           │
└─────────────────────────────┘     └─────────────────────────────┘     └─────────────────────────────┘
         │                                    │                                    │
         │                                    │                                    │
         └────────────────────────────────────┼────────────────────────────────────┘
                                              │
                                              ▼
                              ┌───────────────────────────────────┐
                              │      TRANSACTION_LEDGER           │
                              │   (All Financial Transactions)    │
                              ├───────────────────────────────────┤
                              │ TX-001: investment_deposit $5,000 │
                              │ TX-002: algo_trading_deposit $2K  │
                              │ TX-003: health_wallet_deposit $20K│
                              │ Each has: NFT Token ID            │
                              └───────────────────────────────────┘
```

## Transfer Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    INTERNAL TRANSFER FLOW                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────────────┐
                    │                     EXTERNAL SOURCES                         │
                    │  💳 Credit Card  │  🏦 Bank Transfer  │  ₿ Crypto           │
                    └─────────────────────────┬───────────────────────────────────┘
                                              │
                                              ▼
                    ┌─────────────────────────────────────────────────────────────┐
                    │              /api/unified-payment/deposit                    │
                    │         (Unified Payment Gateway Entry Point)                │
                    └─────────────────────────┬───────────────────────────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
        ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐
        │  🏥 HEALTH WALLET │    │  📈 INVESTMENT    │    │  🤖 ALGO TRADING  │
        │                   │    │                   │    │                   │
        │  For: Medical     │    │  For: Long-term   │    │  For: Bot         │
        │  purchases,       │    │  savings (Index,  │    │  trading          │
        │  health services  │    │  Bonds, Crypto)   │    │  strategies       │
        │                   │    │                   │    │                   │
        │  Balance: $16K    │    │  Balance: $9K     │    │  Balance: $2K     │
        └────────┬──────────┘    └────────┬──────────┘    └────────┬──────────┘
                 │                        │                        │
                 │  INTERNAL TRANSFERS    │                        │
                 │◄───────────────────────►                        │
                 │                        │◄───────────────────────►
                 │◄────────────────────────────────────────────────►
                 │                        │                        │
                 │    payment_method: "internal_transfer"          │
                 │    source_account: "health_wallet"              │
                 │    destination: "investment" or "algo_trading"  │
                 │                        │                        │
                 └────────────────────────┴────────────────────────┘
```

## API Endpoints for Each Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    API → DASHBOARD MAPPING                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  DASHBOARD: savings-portfolio.html                                                                      │
│  ─────────────────────────────────                                                                      │
│  PRIMARY API: /api/investment/unified?customer_id=XXX                                                   │
│                                                                                                         │
│  Returns:                                                                                               │
│    • total_value: $5,000 (investment account total)                                                     │
│    • invested_assets: $5,000 (index + bonds + crypto)                                                   │
│    • index_balance: $3,000                                                                              │
│    • bonds_balance: $1,500                                                                              │
│    • crypto_balance: $500                                                                               │
│    • monthly_contribution: $1,275 (from policies)                                                       │
│    • allocation: {index: 60%, bonds: 30%, crypto: 10%}                                                  │
│                                                                                                         │
│  ⚠️  ISSUE: Returns data from INVESTMENT_ACCOUNTS dict, but allocation chart may need portfolio service │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  DASHBOARD: algo-trading.html                                                                           │
│  ───────────────────────────                                                                            │
│  PRIMARY API: /api/balance/algo-trading?customer_id=XXX                                                 │
│                                                                                                         │
│  Returns:                                                                                               │
│    • available: $2,000 (funds available for trading)                                                    │
│    • in_positions: $0 (funds currently in open trades)                                                  │
│    • total_pnl: $0 (profit/loss from trading)                                                           │
│    • active_bots: 0                                                                                     │
│                                                                                                         │
│  DEPOSIT API: /api/balance/transfer-to-algo (from investment or wallet)                                 │
│  WITHDRAW API: /api/balance/withdraw-from-algo (to investment or wallet)                                │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  DASHBOARD: dashboard.html#billing-settings                                                             │
│  ─────────────────────────────────────────                                                              │
│  "Add Savings" BUTTON API: /api/customer/investment/deposit                                             │
│                                                                                                         │
│  Request:                                                                                               │
│    • customer_id: "CUST-ASAF-001"                                                                       │
│    • amount: 5000                                                                                       │
│    • deposit_type: "additional_savings"                                                                 │
│                                                                                                         │
│  Response:                                                                                              │
│    • success: true                                                                                      │
│    • account_balance: 5000                                                                              │
│    • investment_breakdown: {index: 3000, bonds: 1500, crypto: 500}                                      │
│    • nft_token_id: "NFT-..."                                                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Current Status (asaf@assurance.co.il)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    CURRENT BALANCES                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

                        ┌───────────────────────────────────────────┐
                        │           TOTAL PORTFOLIO                 │
                        │              $27,000                      │
                        └───────────────────┬───────────────────────┘
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              │                             │                             │
              ▼                             ▼                             ▼
   ┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
   │   🏥 HEALTH WALLET  │     │   📈 INVESTMENT     │     │   🤖 ALGO TRADING   │
   │      $16,000        │     │       $9,000        │     │       $2,000        │
   │                     │     │                     │     │                     │
   │   ├─ Spendable      │     │   ├─ Index: $3,000  │     │   ├─ Available      │
   │   │  on medical     │     │   ├─ Bonds: $1,500  │     │   │  for trading    │
   │   │  purchases      │     │   └─ Crypto: $500   │     │   │                 │
   │   │                 │     │                     │     │   └─ P&L: $0        │
   └─────────────────────┘     └─────────────────────┘     └─────────────────────┘
              │                             │                             │
              │                             │                             │
              └─────────────────────────────┴─────────────────────────────┘
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │   INTEGRITY SERVICE       │
                              │   ✅ integrity_valid:     │
                              │      TRUE                 │
                              └───────────────────────────┘
```

## Known Issues

1. **savings-portfolio.html** may show $0 if:
   - Customer has no data in INVESTMENT_ACCOUNTS
   - API authorization fails
   - Frontend doesn't merge unified data correctly

2. **algo-trading.html** deposit/withdraw:
   - Uses `/api/balance/transfer-to-algo` endpoint
   - Source must be `health_wallet` or `investment_account`

3. **Balance Corrections**:
   - Auto-correction can add spurious funds if integrity discrepancy > $10
   - Internal transfers should not affect total but may cause temporary discrepancies
