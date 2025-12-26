BEGIN;

CREATE TABLE IF NOT EXISTS phins.users (
  user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  email citext NOT NULL,
  password_hash text NOT NULL,
  password_salt text NOT NULL,
  role phins.user_role NOT NULL,
  status phins.user_status NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS phins.customers (
  customer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  primary_user_id uuid NULL REFERENCES phins.users(user_id) ON DELETE SET NULL,
  type phins.customer_type NOT NULL DEFAULT 'person',
  legal_name text NOT NULL,
  email citext NOT NULL,
  phone text NULL,
  dob date NULL,
  address_json jsonb NULL,
  kyc_status phins.kyc_status NOT NULL DEFAULT 'unknown',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS phins.applications (
  application_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  status phins.application_status NOT NULL DEFAULT 'draft',
  product_code text NOT NULL,
  form_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  form_snapshot_sha256 char(64) NOT NULL,
  submitted_at timestamptz NULL,
  decision_at timestamptz NULL,
  decision_by_user_id uuid NULL REFERENCES phins.users(user_id) ON DELETE SET NULL,
  risk_assessment text NULL,
  underwriting_notes text NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS phins.policies (
  policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  customer_id uuid NOT NULL REFERENCES phins.customers(customer_id) ON DELETE RESTRICT,
  application_id uuid NOT NULL REFERENCES phins.applications(application_id) ON DELETE RESTRICT,
  product_code text NOT NULL,
  jurisdiction text NOT NULL,
  status phins.policy_status NOT NULL DEFAULT 'pending_underwriting',
  coverage_amount numeric(18,2) NOT NULL CHECK (coverage_amount >= 0),
  currency char(3) NOT NULL DEFAULT 'USD',
  savings_percentage numeric(5,2) NOT NULL CHECK (savings_percentage >= 0 AND savings_percentage <= 99),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, application_id)
);

CREATE TABLE IF NOT EXISTS phins.policy_issuances (
  issuance_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  policy_id uuid NOT NULL REFERENCES phins.policies(policy_id) ON DELETE RESTRICT,
  application_id uuid NOT NULL REFERENCES phins.applications(application_id) ON DELETE RESTRICT,
  status phins.issuance_status NOT NULL DEFAULT 'created',
  issued_at timestamptz NOT NULL DEFAULT now(),
  effective_at timestamptz NULL,
  expires_at timestamptz NULL,
  pricing_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  pricing_snapshot_sha256 char(64) NOT NULL,
  conditions_pdf_sha256 char(64) NULL,
  projection_pdf_sha256 char(64) NULL,
  projection_csv_sha256 char(64) NULL,
  policy_package_pdf_sha256 char(64) NULL,
  created_by_user_id uuid NULL REFERENCES phins.users(user_id) ON DELETE SET NULL,
  UNIQUE (tenant_id, policy_id),
  UNIQUE (tenant_id, application_id)
);

CREATE TABLE IF NOT EXISTS phins.documents (
  document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  owner_customer_id uuid NULL REFERENCES phins.customers(customer_id) ON DELETE SET NULL,
  policy_id uuid NULL REFERENCES phins.policies(policy_id) ON DELETE SET NULL,
  issuance_id uuid NULL REFERENCES phins.policy_issuances(issuance_id) ON DELETE SET NULL,
  application_id uuid NULL REFERENCES phins.applications(application_id) ON DELETE SET NULL,
  kind phins.document_kind NOT NULL,
  sha256 char(64) NOT NULL,
  mime_type text NOT NULL,
  storage_provider phins.storage_provider NOT NULL DEFAULT 'local',
  storage_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS phins.ledger_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  entity_type phins.ledger_entity_type NOT NULL,
  entity_id text NOT NULL,
  event_type text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor_user_id uuid NULL REFERENCES phins.users(user_id) ON DELETE SET NULL,
  idempotency_key text NOT NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS phins.idempotency_keys (
  tenant_id uuid NOT NULL REFERENCES phins.tenants(tenant_id) ON DELETE RESTRICT,
  idempotency_key text NOT NULL,
  request_sha256 char(64) NOT NULL,
  response_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NULL,
  PRIMARY KEY (tenant_id, idempotency_key)
);

COMMIT;
