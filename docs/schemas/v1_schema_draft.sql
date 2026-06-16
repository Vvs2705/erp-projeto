-- ============================================================================
-- ERP-V Initial Physical Database Schema (v1 Draft)
-- Compatibility: PostgreSQL 16+ (fully compatible with Supabase)
-- Design Paradigm: Multi-Tenant Modular Monolith with RLS Isolation
-- ============================================================================

-- ============================================================================
-- 1. EXTENSIONS & SCHEMA CONFIGURATION
-- ============================================================================

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Safe creation of auth schema and fallback functions for non-Supabase local/CI environments
CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS UUID AS $$
BEGIN
  -- Emulate Supabase auth.uid() by checking app.current_user_id when running locally
  RETURN NULLIF(current_setting('app.current_user_id', true), '')::uuid;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION auth.uid() IS 'Fallback helper to emulate Supabase auth.uid() in local development or CI test environments.';

-- ============================================================================
-- 2. DDL CORE HELPER FUNCTIONS & TRIGGERS
-- ============================================================================

CREATE OR REPLACE FUNCTION get_current_tenant_id()
RETURNS UUID AS $$
BEGIN
  -- Extracts, validates and returns the tenant ID from the session parameters
  RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

COMMENT ON FUNCTION get_current_tenant_id() IS 'Extracts and casts the active tenant ID from session context variables.';

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = clock_timestamp();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_updated_at_column() IS 'Trigger function to automatically update the updated_at timestamp on record updates.';

-- ============================================================================
-- 3. TABLES DEFINITION
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Table: tenants
-- ----------------------------------------------------------------------------
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  slug VARCHAR(255) NOT NULL UNIQUE,
  status VARCHAR(50) NOT NULL DEFAULT 'active',
  subscription_price NUMERIC(19, 4) NOT NULL DEFAULT 0.0000,
  billing_limit NUMERIC(19, 4) NOT NULL DEFAULT 0.0000,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT chk_tenants_status CHECK (status IN ('active', 'suspended', 'deactivated')),
  CONSTRAINT chk_tenants_subscription_price CHECK (subscription_price >= 0),
  CONSTRAINT chk_tenants_billing_limit CHECK (billing_limit >= 0)
);

-- ----------------------------------------------------------------------------
-- Table: organizations
-- ----------------------------------------------------------------------------
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  name VARCHAR(255) NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT fk_organizations_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT chk_organizations_status CHECK (status IN ('active', 'suspended', 'deactivated'))
);

-- ----------------------------------------------------------------------------
-- Table: legal_entities
-- ----------------------------------------------------------------------------
CREATE TABLE legal_entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  organization_id UUID NOT NULL,
  name VARCHAR(255) NOT NULL,
  trade_name VARCHAR(255),
  cnpj VARCHAR(14) NOT NULL UNIQUE,
  state_registration VARCHAR(50),
  municipal_registration VARCHAR(50),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT fk_legal_entities_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_legal_entities_organization FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  -- Validates the new Brazilian alphanumeric CNPJ structure (14 raw chars, digits & uppercase letters)
  CONSTRAINT chk_cnpj_format CHECK (cnpj ~ '^[A-Z0-9]{14}$')
);

-- ----------------------------------------------------------------------------
-- Table: users
-- ----------------------------------------------------------------------------
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  status VARCHAR(50) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT chk_users_status CHECK (status IN ('active', 'suspended', 'deactivated')),
  CONSTRAINT chk_email_format CHECK (email ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$')
);

-- ----------------------------------------------------------------------------
-- Table: user_tenants
-- ----------------------------------------------------------------------------
CREATE TABLE user_tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  tenant_id UUID NOT NULL,
  role VARCHAR(50) NOT NULL DEFAULT 'member',
  status VARCHAR(50) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT fk_user_tenants_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_tenants_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT chk_user_tenants_role CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
  CONSTRAINT chk_user_tenants_status CHECK (status IN ('active', 'suspended', 'deactivated')),
  CONSTRAINT uq_user_tenants UNIQUE (user_id, tenant_id)
);

-- ----------------------------------------------------------------------------
-- Table: audit_logs
-- ----------------------------------------------------------------------------
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  user_id UUID,
  action VARCHAR(50) NOT NULL,
  table_name VARCHAR(100) NOT NULL,
  record_id UUID NOT NULL,
  event_category VARCHAR(50) NOT NULL,
  old_values JSONB,
  new_values JSONB,
  client_info JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT fk_audit_logs_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_audit_logs_user FOREIGN KEY (user_id) REFERENCES users(id) ON SET NULL,
  CONSTRAINT chk_audit_logs_category CHECK (event_category IN ('auth', 'data_change', 'security', 'system'))
);

-- ----------------------------------------------------------------------------
-- Table: transactional_outbox
-- ----------------------------------------------------------------------------
CREATE TABLE transactional_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  event_type VARCHAR(255) NOT NULL,
  payload JSONB NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'pending',
  error_message TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  
  CONSTRAINT fk_transactional_outbox_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT chk_transactional_outbox_status CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
  CONSTRAINT chk_transactional_outbox_attempts CHECK (attempts >= 0)
);

-- ============================================================================
-- 4. AUTOMATIC UPDATE TIMESTAMPS TRIGGERS
-- ============================================================================

CREATE TRIGGER trg_tenants_updated_at
  BEFORE UPDATE ON tenants
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_organizations_updated_at
  BEFORE UPDATE ON organizations
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_legal_entities_updated_at
  BEFORE UPDATE ON legal_entities
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_user_tenants_updated_at
  BEFORE UPDATE ON user_tenants
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_transactional_outbox_updated_at
  BEFORE UPDATE ON transactional_outbox
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 5. AUTOMATIC AUDITING TRIGGER & FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION audit_trigger_fn()
RETURNS TRIGGER AS $$
DECLARE
  v_tenant_id UUID;
  v_user_id UUID;
  v_old_jsonb JSONB := NULL;
  v_new_jsonb JSONB := NULL;
  v_record_id UUID;
BEGIN
  -- Determine tenant context
  IF TG_OP = 'DELETE' THEN
    IF TG_TABLE_NAME = 'tenants' THEN
      v_tenant_id := OLD.id;
    ELSIF TG_TABLE_NAME = 'users' THEN
      v_tenant_id := NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
    ELSE
      v_tenant_id := OLD.tenant_id;
    END IF;
    v_record_id := OLD.id;
    v_old_jsonb := row_to_json(OLD)::jsonb;
  ELSE
    IF TG_TABLE_NAME = 'tenants' THEN
      v_tenant_id := NEW.id;
    ELSIF TG_TABLE_NAME = 'users' THEN
      v_tenant_id := NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
    ELSE
      v_tenant_id := NEW.tenant_id;
    END IF;
    v_record_id := NEW.id;
    v_new_jsonb := row_to_json(NEW)::jsonb;
    IF TG_OP = 'UPDATE' THEN
      v_old_jsonb := row_to_json(OLD)::jsonb;
    END IF;
  END IF;

  -- Determine user_id from session context
  BEGIN
    v_user_id := auth.uid();
  EXCEPTION WHEN OTHERS THEN
    v_user_id := NULL;
  END;

  -- Insert audit log
  INSERT INTO audit_logs (
    tenant_id,
    user_id,
    action,
    table_name,
    record_id,
    event_category,
    old_values,
    new_values,
    client_info
  ) VALUES (
    v_tenant_id,
    v_user_id,
    LOWER(TG_OP),
    TG_TABLE_NAME,
    v_record_id,
    'data_change',
    v_old_jsonb,
    v_new_jsonb,
    jsonb_build_object(
      'ip_address', inet_client_addr(),
      'user_agent', NULLIF(current_setting('request.headers', true), '')
    )
  );

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  ELSE
    RETURN NEW;
  END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION audit_trigger_fn() IS 'Automatically logs data mutations (INSERT, UPDATE, DELETE) into the audit_logs table.';

-- Attach Audit Triggers to target tables
CREATE TRIGGER trg_audit_tenants
  AFTER INSERT OR UPDATE OR DELETE ON tenants
  FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();

CREATE TRIGGER trg_audit_organizations
  AFTER INSERT OR UPDATE OR DELETE ON organizations
  FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();

CREATE TRIGGER trg_audit_legal_entities
  AFTER INSERT OR UPDATE OR DELETE ON legal_entities
  FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();

CREATE TRIGGER trg_audit_users
  AFTER INSERT OR UPDATE OR DELETE ON users
  FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();

CREATE TRIGGER trg_audit_user_tenants
  AFTER INSERT OR UPDATE OR DELETE ON user_tenants
  FOR EACH ROW EXECUTE FUNCTION audit_trigger_fn();

-- ============================================================================
-- 6. INDEXES FOR PERFORMANCE & INTEGRITY
-- ============================================================================

-- Organizations indexes
CREATE INDEX idx_organizations_tenant_id ON organizations(tenant_id);

-- Legal Entities indexes
CREATE INDEX idx_legal_entities_tenant_id ON legal_entities(tenant_id);
CREATE INDEX idx_legal_entities_organization_id ON legal_entities(organization_id);
CREATE INDEX idx_legal_entities_tenant_org ON legal_entities(tenant_id, organization_id);

-- User Tenants indexes
CREATE INDEX idx_user_tenants_tenant_id ON user_tenants(tenant_id);
CREATE INDEX idx_user_tenants_user_id ON user_tenants(user_id);

-- Audit Logs indexes
-- Optimized for chronological audit trail dashboards filtering by tenant
CREATE INDEX idx_audit_logs_tenant_created ON audit_logs(tenant_id, created_at DESC);
-- Optimized for entity change history lookup
CREATE INDEX idx_audit_logs_table_record ON audit_logs(table_name, record_id);

-- Transactional Outbox indexes
-- Highly optimized for event relay polling (looks up only pending items)
CREATE INDEX idx_transactional_outbox_status_created ON transactional_outbox(status, created_at)
  WHERE status = 'pending';
CREATE INDEX idx_transactional_outbox_tenant_status ON transactional_outbox(tenant_id, status);

-- ============================================================================
-- 7. ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

-- Enable RLS for all sensitive tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactional_outbox ENABLE ROW LEVEL SECURITY;

-- Tenants policies
CREATE POLICY tenant_isolation ON tenants
  FOR ALL
  USING (id = get_current_tenant_id())
  WITH CHECK (id = get_current_tenant_id());

-- Organizations policies
CREATE POLICY organization_tenant_isolation ON organizations
  FOR ALL
  USING (tenant_id = get_current_tenant_id())
  WITH CHECK (tenant_id = get_current_tenant_id());

-- Legal Entities policies
CREATE POLICY legal_entity_tenant_isolation ON legal_entities
  FOR ALL
  USING (tenant_id = get_current_tenant_id())
  WITH CHECK (tenant_id = get_current_tenant_id());

-- Users policies
CREATE POLICY user_tenant_isolation ON users
  FOR ALL
  USING (
    id = auth.uid()
    OR EXISTS (
      SELECT 1 FROM user_tenants
      WHERE user_tenants.user_id = users.id
        AND user_tenants.tenant_id = get_current_tenant_id()
    )
  );

-- User Tenants policies
CREATE POLICY user_tenants_isolation ON user_tenants
  FOR ALL
  USING (
    tenant_id = get_current_tenant_id()
    OR user_id = auth.uid()
  )
  WITH CHECK (
    tenant_id = get_current_tenant_id()
  );

-- Audit Logs policies
CREATE POLICY audit_log_tenant_isolation ON audit_logs
  FOR SELECT
  USING (tenant_id = get_current_tenant_id());

CREATE POLICY audit_log_insert_policy ON audit_logs
  FOR INSERT
  WITH CHECK (tenant_id = get_current_tenant_id());

-- Transactional Outbox policies
CREATE POLICY outbox_tenant_isolation ON transactional_outbox
  FOR ALL
  USING (tenant_id = get_current_tenant_id())
  WITH CHECK (tenant_id = get_current_tenant_id());

-- Note for background outbox relays and sync workers:
-- They should connect using a superuser, service_role or a custom role with
-- "BYPASSRLS" attribute set to allow cross-tenant queries.

-- ============================================================================
-- 8. DATABASE DOCUMENTATION & COMMENTS
-- ============================================================================

-- Table comments
COMMENT ON TABLE tenants IS 'Root entity defining the logical boundary for database multi-tenant isolation and access control.';
COMMENT ON TABLE organizations IS 'Sub-divisions within a tenant representing departments, business units or geographic branches.';
COMMENT ON TABLE legal_entities IS 'Official legal entities/companies holding active tax IDs (CNPJ) within an organization.';
COMMENT ON TABLE users IS 'Master repository of platform users.';
COMMENT ON TABLE user_tenants IS 'Association table linking users to tenants with specific functional roles.';
COMMENT ON TABLE audit_logs IS 'System audit trail logging transactional state changes, mutations, and auditing metadata.';
COMMENT ON TABLE transactional_outbox IS 'Transactional Outbox pattern message queue for reliable event publishing and event-driven architecture.';

-- Columns: tenants
COMMENT ON COLUMN tenants.id IS 'Primary key of the tenant (UUID v4).';
COMMENT ON COLUMN tenants.name IS 'Display name of the tenant.';
COMMENT ON COLUMN tenants.slug IS 'Unique URL-safe sub-domain/path prefix allocated to the tenant.';
COMMENT ON COLUMN tenants.status IS 'Active lifecycle status of the tenant (active, suspended, deactivated).';
COMMENT ON COLUMN tenants.subscription_price IS 'Financial price of the active subscription per tenant (NUMERIC 19,4).';
COMMENT ON COLUMN tenants.billing_limit IS 'Max credit threshold allocated to the tenant (NUMERIC 19,4).';
COMMENT ON COLUMN tenants.created_at IS 'Timestamp denoting tenant record registration.';
COMMENT ON COLUMN tenants.updated_at IS 'Timestamp denoting last modification date of the tenant.';

-- Columns: organizations
COMMENT ON COLUMN organizations.id IS 'Primary key of the organization (UUID v4).';
COMMENT ON COLUMN organizations.tenant_id IS 'Foreign key referencing owning tenant.';
COMMENT ON COLUMN organizations.name IS 'Commercial name of the organizational subunit.';
COMMENT ON COLUMN organizations.status IS 'Active lifecycle status of the organization.';
COMMENT ON COLUMN organizations.created_at IS 'Timestamp denoting organization creation.';
COMMENT ON COLUMN organizations.updated_at IS 'Timestamp denoting last organization update.';

-- Columns: legal_entities
COMMENT ON COLUMN legal_entities.id IS 'Primary key of the legal entity (UUID v4).';
COMMENT ON COLUMN legal_entities.tenant_id IS 'Foreign key referencing owning tenant.';
COMMENT ON COLUMN legal_entities.organization_id IS 'Foreign key referencing associated organizational unit.';
COMMENT ON COLUMN legal_entities.name IS 'Registered corporate business name (Razão Social).';
COMMENT ON COLUMN legal_entities.trade_name IS 'Informal trade name (Nome Fantasia).';
COMMENT ON COLUMN legal_entities.cnpj IS 'Brazilian Corporate Taxpayer ID (CNPJ), alphanumeric, raw 14 characters without formatting.';
COMMENT ON COLUMN legal_entities.state_registration IS 'State tax registry registration (Inscrição Estadual).';
COMMENT ON COLUMN legal_entities.municipal_registration IS 'Municipal tax registry registration (Inscrição Municipal).';
COMMENT ON COLUMN legal_entities.created_at IS 'Timestamp of legal entity creation.';
COMMENT ON COLUMN legal_entities.updated_at IS 'Timestamp of last update.';

-- Columns: users
COMMENT ON COLUMN users.id IS 'Primary key of the user (designed to match external auth provider IDs like Supabase auth.users).';
COMMENT ON COLUMN users.name IS 'Full name of the user.';
COMMENT ON COLUMN users.email IS 'Unique email address verified for user login.';
COMMENT ON COLUMN users.status IS 'Operational user state (active, suspended, deactivated).';
COMMENT ON COLUMN users.created_at IS 'Timestamp of user registration.';
COMMENT ON COLUMN users.updated_at IS 'Timestamp of last user update.';

-- Columns: user_tenants
COMMENT ON COLUMN user_tenants.id IS 'Primary key of the relationship link.';
COMMENT ON COLUMN user_tenants.user_id IS 'Foreign key referencing target user.';
COMMENT ON COLUMN user_tenants.tenant_id IS 'Foreign key referencing target tenant.';
COMMENT ON COLUMN user_tenants.role IS 'Security classification and role associated with user within the tenant context (owner, admin, member, viewer).';
COMMENT ON COLUMN user_tenants.status IS 'Active association lifecycle state.';
COMMENT ON COLUMN user_tenants.created_at IS 'Timestamp of association link creation.';
COMMENT ON COLUMN user_tenants.updated_at IS 'Timestamp of association link update.';

-- Columns: audit_logs
COMMENT ON COLUMN audit_logs.id IS 'Primary key of the audit log entry.';
COMMENT ON COLUMN audit_logs.tenant_id IS 'Foreign key referencing parent tenant.';
COMMENT ON COLUMN audit_logs.user_id IS 'Foreign key referencing user who executed the mutation.';
COMMENT ON COLUMN audit_logs.action IS 'Standard execution operation details (insert, update, delete).';
COMMENT ON COLUMN audit_logs.table_name IS 'Target database table mutated.';
COMMENT ON COLUMN audit_logs.record_id IS 'UUID primary key of the modified database record.';
COMMENT ON COLUMN audit_logs.event_category IS 'Audit event taxonomy classification.';
COMMENT ON COLUMN audit_logs.old_values IS 'Pre-mutation JSON data state.';
COMMENT ON COLUMN audit_logs.new_values IS 'Post-mutation JSON data state.';
COMMENT ON COLUMN audit_logs.client_info IS 'JSON document capturing origin network IP and agent signature.';
COMMENT ON COLUMN audit_logs.created_at IS 'Immutable event timestamp.';

-- Columns: transactional_outbox
COMMENT ON COLUMN transactional_outbox.id IS 'Primary key of the outbox payload.';
COMMENT ON COLUMN transactional_outbox.tenant_id IS 'Foreign key referencing parent tenant.';
COMMENT ON COLUMN transactional_outbox.event_type IS 'Logical classification namespace for routing (e.g. legal_entity.created).';
COMMENT ON COLUMN transactional_outbox.payload IS 'Serialized JSON content containing the payload.';
COMMENT ON COLUMN transactional_outbox.status IS 'Processing status state machine (pending, processing, completed, failed).';
COMMENT ON COLUMN transactional_outbox.error_message IS 'Optional execution stack trace or error message during publication.';
COMMENT ON COLUMN transactional_outbox.attempts IS 'Total publication retries.';
COMMENT ON COLUMN transactional_outbox.processed_at IS 'Execution completion timestamp.';
COMMENT ON COLUMN transactional_outbox.created_at IS 'Outbox message queue entry timestamp.';
COMMENT ON COLUMN transactional_outbox.updated_at IS 'Last modification timestamp.';
