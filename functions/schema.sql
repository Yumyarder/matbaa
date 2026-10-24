-- The site's counter (functions/api/sayac.js): one row per book a reader's
-- Matbaa set. No address, no title: the genre, the day, the hour.
CREATE TABLE IF NOT EXISTS dizilen (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tur TEXT NOT NULL,
  gun TEXT NOT NULL,     -- 2026-10-24
  saat TEXT NOT NULL     -- 2026-10-24T09 (UTC)
);
CREATE INDEX IF NOT EXISTS dizilen_gun ON dizilen (gun);
