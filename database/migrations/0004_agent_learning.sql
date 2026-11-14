-- =============================================================================
-- Agent learning profile: durable, organisation-level guidance the agents may
-- read when planning and wording reports. It never changes how figures are
-- calculated; deterministic code and reconciliation remain the source of truth.
-- =============================================================================

ALTER TABLE organisations
    ADD COLUMN IF NOT EXISTS learning_profile JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE organisations
    DROP CONSTRAINT IF EXISTS organisations_learning_profile_object;

ALTER TABLE organisations
    ADD CONSTRAINT organisations_learning_profile_object
    CHECK (jsonb_typeof(learning_profile) = 'object');

COMMENT ON COLUMN organisations.learning_profile IS
    'Owner/admin-maintained guidance for agents: business context, glossary, analysis preferences, report style and lessons from feedback. Read by planning and narrative prompts; never used to calculate figures.';
