-- Derived sector scores only. Provider responses, credentials and local paths are prohibited.
CREATE TABLE IF NOT EXISTS sector_rotation_snapshots (
  observed_at TEXT NOT NULL,
  market_date TEXT NOT NULL,
  session TEXT NOT NULL CHECK (session IN ('intraday', 'close')),
  universe TEXT NOT NULL CHECK (universe IN ('industry', 'concept')),
  sector_id TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  strength INTEGER CHECK (strength IS NULL OR strength BETWEEN 0 AND 100),
  strength_rank_key REAL CHECK (strength_rank_key IS NULL OR strength_rank_key BETWEEN 0 AND 100),
  opportunity INTEGER CHECK (opportunity IS NULL OR opportunity BETWEEN 0 AND 100),
  opportunity_rank_key REAL CHECK (opportunity_rank_key IS NULL OR opportunity_rank_key BETWEEN 0 AND 100),
  risk INTEGER CHECK (risk IS NULL OR risk BETWEEN 0 AND 100),
  risk_rank_key REAL CHECK (risk_rank_key IS NULL OR risk_rank_key BETWEEN 0 AND 100),
  heat_state TEXT CHECK (heat_state IS NULL OR heat_state IN ('cold', 'neutral', 'warming', 'active', 'crowded')),
  completeness INTEGER NOT NULL CHECK (completeness BETWEEN 0 AND 100),
  strength_rank INTEGER CHECK (strength_rank IS NULL OR strength_rank BETWEEN 1 AND 75),
  opportunity_rank INTEGER CHECK (opportunity_rank IS NULL OR opportunity_rank BETWEEN 1 AND 75),
  risk_rank INTEGER CHECK (risk_rank IS NULL OR risk_rank BETWEEN 1 AND 75),
  official_close INTEGER NOT NULL CHECK (official_close IN (0, 1)),
  cold_start INTEGER NOT NULL CHECK (cold_start IN (0, 1)),
  valid_closes INTEGER NOT NULL CHECK (valid_closes >= 0),
  improvement_evidence INTEGER NOT NULL CHECK (improvement_evidence >= 0),
  scoring_version TEXT NOT NULL,
  universe_version TEXT NOT NULL,
  components_json TEXT NOT NULL CHECK (json_valid(components_json)),
  missing_json TEXT NOT NULL CHECK (json_valid(missing_json)),
  contributors_json TEXT NOT NULL CHECK (json_valid(contributors_json)),
  leaderboard_json TEXT NOT NULL CHECK (json_valid(leaderboard_json)),
  provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),
  created_at TEXT NOT NULL,
  PRIMARY KEY (observed_at, universe, sector_id, scoring_version)
);

CREATE INDEX IF NOT EXISTS idx_sector_rotation_latest
ON sector_rotation_snapshots(universe, scoring_version, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_sector_rotation_market_date
ON sector_rotation_snapshots(market_date DESC, universe, scoring_version, official_close);

CREATE INDEX IF NOT EXISTS idx_sector_rotation_strength_rank
ON sector_rotation_snapshots(universe, scoring_version, observed_at DESC, strength_rank);

CREATE INDEX IF NOT EXISTS idx_sector_rotation_opportunity_rank
ON sector_rotation_snapshots(universe, scoring_version, observed_at DESC, opportunity_rank);

CREATE INDEX IF NOT EXISTS idx_sector_rotation_risk_rank
ON sector_rotation_snapshots(universe, scoring_version, observed_at DESC, risk_rank);
