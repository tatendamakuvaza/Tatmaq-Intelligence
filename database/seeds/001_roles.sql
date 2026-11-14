-- =============================================================================
-- System roles. Idempotent: re-applied on every migrate, so editing a permission
-- here and running the migration script is how role permissions are changed.
--
-- Every member, whatever their role, can read their organisation's data. The
-- permissions below govern what each role may additionally *do*.
-- =============================================================================

INSERT INTO roles (name, description, permissions) VALUES
(
    'owner',
    'Full control of the organisation.',
    '{"organisation:manage": true, "members:manage": true, "workspaces:create": true,
      "datasets:upload": true, "analysis:run": true, "analysis:cancel": true,
      "reports:download": true, "audit:view": true}'
),
(
    'admin',
    'Manages workspaces and members; can do everything an analyst can.',
    '{"organisation:manage": true, "members:manage": true, "workspaces:create": true,
      "datasets:upload": true, "analysis:run": true, "analysis:cancel": true,
      "reports:download": true, "audit:view": true}'
),
(
    'analyst',
    'Uploads datasets, runs analyses and downloads reports.',
    '{"datasets:upload": true, "analysis:run": true, "analysis:cancel": true,
      "reports:download": true}'
),
(
    'viewer',
    'Read-only: can view results and download reports.',
    '{"reports:download": true}'
)
ON CONFLICT (name) DO UPDATE
SET description = EXCLUDED.description,
    permissions = EXCLUDED.permissions;
