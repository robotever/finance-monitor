-- Additive, derived-only v4 publication. v3 data remains untouched.
CREATE TABLE IF NOT EXISTS sector_rotation_v4_manifests (
 batch_id TEXT PRIMARY KEY,
 observed_at TEXT NOT NULL, market_date TEXT NOT NULL,
 session TEXT NOT NULL CHECK(session IN ('intraday','close')),
 official_close INTEGER NOT NULL CHECK(official_close IN (0,1)),
 schema_version TEXT NOT NULL CHECK(schema_version='market-dashboard-v4'),
 scoring_version TEXT NOT NULL CHECK(scoring_version='sector-score-v0.3'),
 universe_version TEXT NOT NULL CHECK(universe_version='sector-universe-ths-v1'),
 feature_version TEXT NOT NULL CHECK(feature_version='sector-features-ths-v1'),
 membership_version TEXT NOT NULL CHECK(membership_version='sector-membership-ths-v1'),
 industry_count INTEGER NOT NULL CHECK(industry_count=90),
 concept_count INTEGER NOT NULL CHECK(concept_count BETWEEN 1 AND 10000),
 chunk_count INTEGER NOT NULL CHECK(chunk_count BETWEEN 1 AND 10090),
 digest TEXT NOT NULL CHECK(length(digest)=64),
 manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
 status TEXT NOT NULL DEFAULT 'staging' CHECK(status IN ('staging','active')),
 created_at TEXT NOT NULL, activated_at TEXT
);
CREATE TABLE IF NOT EXISTS sector_rotation_v4_chunks (
 batch_id TEXT NOT NULL REFERENCES sector_rotation_v4_manifests(batch_id),
 chunk_index INTEGER NOT NULL CHECK(chunk_index>=0),
 digest TEXT NOT NULL CHECK(length(digest)=64),
 row_count INTEGER NOT NULL CHECK(row_count BETWEEN 1 AND 50),
 rows_json TEXT NOT NULL CHECK(json_valid(rows_json)),
 PRIMARY KEY(batch_id,chunk_index)
);
CREATE TABLE IF NOT EXISTS sector_rotation_v4_sectors (
 batch_id TEXT NOT NULL REFERENCES sector_rotation_v4_manifests(batch_id),
 chunk_index INTEGER NOT NULL,
 universe TEXT NOT NULL CHECK(universe IN ('industry','concept')),
 sector_id TEXT NOT NULL, sector_name TEXT NOT NULL,
 strength REAL CHECK(strength IS NULL OR strength BETWEEN 0 AND 100),
 opportunity REAL CHECK(opportunity IS NULL OR opportunity BETWEEN 0 AND 100),
 risk REAL CHECK(risk IS NULL OR risk BETWEEN 0 AND 100),
 completeness INTEGER NOT NULL CHECK(completeness BETWEEN 0 AND 100),
 strength_rank INTEGER CHECK(strength_rank IS NULL OR strength_rank BETWEEN 1 AND 10000),
 opportunity_rank INTEGER CHECK(opportunity_rank IS NULL OR opportunity_rank BETWEEN 1 AND 10000),
 risk_rank INTEGER CHECK(risk_rank IS NULL OR risk_rank BETWEEN 1 AND 10000),
 row_json TEXT NOT NULL CHECK(json_valid(row_json)),
 PRIMARY KEY(batch_id,universe,sector_id),
 FOREIGN KEY(batch_id,chunk_index) REFERENCES sector_rotation_v4_chunks(batch_id,chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_sector_v4_active ON sector_rotation_v4_manifests(status,scoring_version,universe_version,observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sector_v4_universe ON sector_rotation_v4_sectors(batch_id,universe,sector_id);
-- Enforce immutability even when uploads race an activation.
CREATE TRIGGER IF NOT EXISTS sector_v4_chunk_frozen BEFORE INSERT ON sector_rotation_v4_chunks
WHEN (SELECT status FROM sector_rotation_v4_manifests WHERE batch_id=NEW.batch_id)!='staging'
BEGIN SELECT RAISE(ABORT,'BATCH_FROZEN'); END;
CREATE TRIGGER IF NOT EXISTS sector_v4_row_frozen BEFORE INSERT ON sector_rotation_v4_sectors
WHEN (SELECT status FROM sector_rotation_v4_manifests WHERE batch_id=NEW.batch_id)!='staging'
BEGIN SELECT RAISE(ABORT,'BATCH_FROZEN'); END;
CREATE TRIGGER IF NOT EXISTS sector_v4_chunk_no_update BEFORE UPDATE ON sector_rotation_v4_chunks BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CHUNK'); END;
CREATE TRIGGER IF NOT EXISTS sector_v4_row_no_update BEFORE UPDATE ON sector_rotation_v4_sectors BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ROW'); END;
CREATE TRIGGER IF NOT EXISTS sector_v4_chunk_no_delete BEFORE DELETE ON sector_rotation_v4_chunks BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CHUNK'); END;
CREATE TRIGGER IF NOT EXISTS sector_v4_row_no_delete BEFORE DELETE ON sector_rotation_v4_sectors BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ROW'); END;
