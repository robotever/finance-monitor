-- Independent research inputs. Existing sector documents are not modified.
CREATE TABLE IF NOT EXISTS radar_input_batches (
 observed_at TEXT PRIMARY KEY,
 market_date TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS radar_input_date ON radar_input_batches(market_date DESC,observed_at DESC);
