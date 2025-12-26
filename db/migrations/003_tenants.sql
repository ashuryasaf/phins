BEGIN;

CREATE TABLE IF NOT EXISTS phins.tenants (
  tenant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  type text NOT NULL CHECK (type IN ('b2c','broker','employer','supplier')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Default tenant (B2C). Keep this stable for app code.
INSERT INTO phins.tenants (tenant_id, name, type)
VALUES ('00000000-0000-0000-0000-000000000001', 'PHINS Default', 'b2c')
ON CONFLICT (tenant_id) DO NOTHING;

COMMIT;
