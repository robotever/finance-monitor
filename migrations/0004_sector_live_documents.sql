CREATE TABLE IF NOT EXISTS sector_live_generations (
 generation TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, observed_at TEXT NOT NULL,
 digest TEXT NOT NULL, document_count INTEGER NOT NULL CHECK(document_count=491),
 activated_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sector_live_parts (
 generation TEXT NOT NULL REFERENCES sector_live_generations(generation),
 document_key TEXT NOT NULL, part_index INTEGER NOT NULL, part_count INTEGER NOT NULL,
 digest TEXT NOT NULL, part_digest TEXT NOT NULL, gzip_base64 TEXT NOT NULL,
 PRIMARY KEY(generation,document_key,part_index)
);
CREATE TRIGGER IF NOT EXISTS sector_live_parts_immutable BEFORE UPDATE ON sector_live_parts
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_PART'); END;
CREATE TRIGGER IF NOT EXISTS sector_live_parts_conflict BEFORE INSERT ON sector_live_parts
 WHEN EXISTS(SELECT 1 FROM sector_live_parts WHERE generation=NEW.generation AND document_key=NEW.document_key
 AND (digest<>NEW.digest OR part_count<>NEW.part_count OR (part_index=NEW.part_index AND (part_digest<>NEW.part_digest OR gzip_base64<>NEW.gzip_base64))))
 BEGIN SELECT RAISE(ABORT,'PART_CONFLICT'); END;
CREATE TRIGGER IF NOT EXISTS sector_live_parts_sealed BEFORE INSERT ON sector_live_parts
 WHEN EXISTS(SELECT 1 FROM sector_live_generations WHERE generation=NEW.generation AND activated_at IS NOT NULL)
 AND NOT EXISTS(SELECT 1 FROM sector_live_parts WHERE generation=NEW.generation AND document_key=NEW.document_key AND part_index=NEW.part_index)
 BEGIN SELECT RAISE(ABORT,'SEALED_GENERATION'); END;
CREATE TABLE IF NOT EXISTS sector_live_documents (
 generation TEXT NOT NULL, document_key TEXT NOT NULL, digest TEXT NOT NULL,
 PRIMARY KEY(generation,document_key)
);
CREATE TABLE IF NOT EXISTS sector_live_active (id INTEGER PRIMARY KEY CHECK(id=1),generation TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sector_live_health (id INTEGER PRIMARY KEY CHECK(id=1),status_json TEXT NOT NULL);
