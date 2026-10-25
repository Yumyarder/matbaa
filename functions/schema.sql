-- The site's counter (functions/api/sayac.js): one row per book a reader's
-- Matbaa set. No address, no title: the genre, the day, the hour.
CREATE TABLE IF NOT EXISTS dizilen (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tur TEXT NOT NULL,
  gun TEXT NOT NULL,     -- 2026-10-24
  saat TEXT NOT NULL     -- 2026-10-24T09 (UTC)
);
CREATE INDEX IF NOT EXISTS dizilen_gun ON dizilen (gun);

-- The count per genre, kept as books come, so reading the totals does not
-- count every row of dizilen. Rebuilt from dizilen by the last statement,
-- which makes this file safe to run again on the live database.
CREATE TABLE IF NOT EXISTS sayim (
  tur TEXT PRIMARY KEY,
  n INTEGER NOT NULL
);
INSERT INTO sayim (tur, n) SELECT tur, COUNT(*) FROM dizilen WHERE true GROUP BY tur
  ON CONFLICT(tur) DO UPDATE SET n = excluded.n;
