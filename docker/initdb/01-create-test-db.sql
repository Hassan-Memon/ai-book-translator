-- Runs once, on first start of an empty Postgres volume.
-- The app uses translatebook_v2 (POSTGRES_DB); the test suite uses translatebook_test.
CREATE DATABASE translatebook_test OWNER translatebook;
