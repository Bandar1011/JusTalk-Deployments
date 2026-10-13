BEGIN;
CREATE EXTENSION IF NOT EXISTS pgtap WITH SCHEMA extensions;
SELECT extensions.plan(1);
SELECT extensions.ok(current_setting('server_version_num')::integer >= 170000, 'supported PostgreSQL');
SELECT * FROM extensions.finish();
ROLLBACK;
