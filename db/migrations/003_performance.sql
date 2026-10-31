-- Store each visit's number of priced quotes, so the speed check no longer counts quotes by scanning
-- every chunk of core.price_quotes, and index the columns the quality checks look up.
ALTER TABLE core.visits ADD COLUMN IF NOT EXISTS n_quotes integer NOT NULL DEFAULT 0;

UPDATE core.visits v SET n_quotes = c.n
FROM (SELECT visit_id, count(*) AS n FROM core.price_quotes WHERE vendor_id <> 0 GROUP BY visit_id) c
WHERE c.visit_id = v.id;

CREATE INDEX IF NOT EXISTS visits_enumerator_date_idx ON core.visits (enumerator_id, visit_date DESC);
CREATE INDEX IF NOT EXISTS visits_photo_hash_idx ON core.visits (photo_hash);
