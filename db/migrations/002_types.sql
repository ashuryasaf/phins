BEGIN;

DO $$ BEGIN
  CREATE TYPE phins.user_role AS ENUM ('customer','admin','underwriter','claims','accountant','broker','supplier_admin');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.user_status AS ENUM ('active','disabled','locked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.customer_type AS ENUM ('person','organization');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.kyc_status AS ENUM ('unknown','pending','verified','rejected');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.application_status AS ENUM ('draft','submitted','uw_pending','uw_info_required','uw_approved','uw_rejected','withdrawn');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.policy_status AS ENUM ('pending_underwriting','billing_pending','billing_review','in_force','lapsed','cancelled','expired','rejected');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.issuance_status AS ENUM ('created','billing_pending','in_force','voided');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.document_kind AS ENUM ('master_conditions_pdf','policy_terms_pdf','policy_package_pdf','projection_pdf','projection_csv','signature_png','claim_attachment');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.invoice_status AS ENUM ('outstanding','under_review','paid','void','refunded');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.invoice_type AS ENUM ('first_premium','recurring_premium','topup','fee');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.billing_link_status AS ENUM ('active','revoked','expired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.payment_attempt_status AS ENUM ('attempted','authorized','captured','failed','review');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.wallet_txn_kind AS ENUM ('deposit','withdrawal','claim_payout','fee');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.claim_status AS ENUM ('fnol_received','triage','docs_pending','under_review','approved','denied','paid','closed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.nft_status AS ENUM ('issued','transferred','burned','revoked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.storage_provider AS ENUM ('local','s3');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE phins.ledger_entity_type AS ENUM ('application','policy','issuance','invoice','payment','claim','nft','document');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMIT;
