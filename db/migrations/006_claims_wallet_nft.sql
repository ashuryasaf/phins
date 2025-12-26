BEGIN;

CREATE TABLE IF NOT EXISTS phins.wallet_transactions (
  wallet_txn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  policy_id uuid NULL REFERENCES phins.policies(policy_id) ON DELETE SET NULL,
  issuance_id uuid NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE SET NULL,
  kind phins.wallet_txn_kind NOT NULL,
  amount numeric(18,2) NOT NULL,
  currency char(3) NOT NULL DEFAULT 'USD',
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS phins.claims (
  claim_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  policy_id uuid NOT NULL REFERENCES phins.policies(policy_id) ON DELETE RESTRICT,
  issuance_id uuid NOT NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE RESTRICT,
  customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  status phins.claim_status NOT NULL DEFAULT 'fnol_received',
  type text NOT NULL,
  claimed_amount numeric(18,2) NOT NULL CHECK (claimed_amount >= 0),
  approved_amount numeric(18,2) NULL,
  paid_amount numeric(18,2) NULL,
  description text NULL,
  fraud_score int NULL,
  fraud_reasons jsonb NULL,
  filed_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz NULL,
  paid_at timestamptz NULL,
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS phins.nft_tokens (
  nft_token_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  issuance_id uuid NOT NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE RESTRICT,
  policy_id uuid NOT NULL REFERENCES phins.policies(policy_id) ON DELETE RESTRICT,
  current_owner_customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  status phins.nft_status NOT NULL DEFAULT 'issued',
  chain text NOT NULL,
  contract_address text NULL,
  token_id text NOT NULL,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, issuance_id),
  UNIQUE (tenant_id, token_id)
);

CREATE TABLE IF NOT EXISTS phins.nft_transfers (
  transfer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  nft_token_id uuid NOT NULL REFERENCES phins.nft_tokens(nft_token_id) ON DELETE RESTRICT,
  from_customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  to_customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  reason text NULL,
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);

COMMIT;
