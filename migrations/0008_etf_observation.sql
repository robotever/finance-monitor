-- Isolated daily ETF observation; leaves sector and radar score tables unchanged.
CREATE TABLE IF NOT EXISTS etf_observation_latest (
 id INTEGER PRIMARY KEY CHECK (id=1),
 observed_at TEXT NOT NULL,
 market_date TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
