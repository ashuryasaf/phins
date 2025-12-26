-- IMPORTANT: These are safe and can be run repeatedly.
-- We use CONCURRENTLY to avoid long locks on large tables.
-- NOTE: CONCURRENTLY cannot run inside a transaction.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_tenant_role ON phins.users(tenant_id, role);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_tenant_email ON phins.customers(tenant_id, email);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_applications_tenant_customer ON phins.applications(tenant_id, customer_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_applications_tenant_status ON phins.applications(tenant_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_policies_tenant_customer ON phins.policies(tenant_id, customer_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_policies_tenant_status ON phins.policies(tenant_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_issuances_tenant_status ON phins.policy_issuances(tenant_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_documents_tenant_owner ON phins.documents(tenant_id, owner_customer_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_entity_time ON phins.ledger_events(tenant_id, entity_type, entity_id, occurred_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_tenant_status ON phins.billing_invoices(tenant_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_claims_tenant_status ON phins.claims(tenant_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nft_tenant_owner ON phins.nft_tokens(tenant_id, current_owner_customer_id);
