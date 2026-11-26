CREATE TABLE IF NOT EXISTS market_observation_latest (
 id INTEGER PRIMARY KEY CHECK(id=1),
 market_date TEXT NOT NULL,
 snapshot_at TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
