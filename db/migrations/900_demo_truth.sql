-- Demo only: ground truth written by the synthetic generator. Never present in production.
CREATE SCHEMA IF NOT EXISTS truth;

CREATE TABLE truth.params      (key text PRIMARY KEY, value jsonb NOT NULL);
CREATE TABLE truth.events      (code text PRIMARY KEY, commodity text, market text,
                                start_date date NOT NULL, end_date date NOT NULL, description text NOT NULL);
CREATE TABLE truth.true_prices (day date, commodity text, market text, price double precision,
                                PRIMARY KEY (day, commodity, market));
CREATE TABLE truth.misconduct  (kobo_uuid text PRIMARY KEY, enumerator text NOT NULL, kind text NOT NULL);
CREATE TABLE truth.typos       (kobo_uuid text, commodity text, vendor text, PRIMARY KEY (kobo_uuid, commodity, vendor));
