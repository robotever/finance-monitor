-- Daily archive lookup uses existing immutable manifest metadata.
CREATE INDEX IF NOT EXISTS sector_live_daily_lookup
 ON sector_live_generations(json_extract(manifest_json,'$.storageMode'),json_extract(manifest_json,'$.marketDate'),observed_at DESC)
 WHERE activated_at IS NOT NULL;
