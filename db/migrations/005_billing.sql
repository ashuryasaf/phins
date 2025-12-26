BEGIN;

CREATE TABLE IF NOT EXISTS phins.billing_invoices (
  invoice_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  policy_id uuid NOT NULL REFERENCES phins.policies(policy_id) ON DELETE RESTRICT,
  issuance_id uuid NOT NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE RESTRICT,
  customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  type phins.invoice_type NOT NULL,
  amount numeric(18,2) NOT NULL CHECK (amount >= 0),
  currency char(3) NOT NULL DEFAULT 'USD',
  status phins.invoice_status NOT NULL DEFAULT 'outstanding',
  due_at timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  paid_at timestamptz NULL
);

CREATE TABLE IF NOT EXISTS phins.billing_links (
  billing_link_token text PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  invoice_id uuid NOT NULL REFERENCES phins.billing_invoices(invoice_id) ON DELETE RESTRICT,
  policy_id uuid NOT NULL REFERENCES phins.policies(policy_id) ON DELETE RESTRICT,
  issuance_id uuid NOT NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE RESTRICT,
  status phins.billing_link_status NOT NULL DEFAULT 'active',
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS phins.payment_attempts (
  payment_attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  invoice_id uuid NOT NULL REFERENCES phins.billing_invoices(invoice_id) ON DELETE RESTRICT,
  billing_link_token text NULL,
  status phins.payment_attempt_status NOT NULL DEFAULT 'attempted',
  risk_score int NULL,
  risk_reasons jsonb NULL,
  billing_details_json jsonb NULL,
  ip text NULL,
  user_agent text NULL,
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS phins.premium_allocations (
  allocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  issuance_id uuid NOT NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE RESTRICT,
  invoice_id uuid NOT NULL REFERENCES phins.billing_invoices(invoice_id) ON DELETE RESTRICT,
  risk_amount numeric(18,2) NOT NULL DEFAULT 0,
  savings_amount numeric(18,2) NOT NULL DEFAULT 0,
  fee_amount numeric(18,2) NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
