"""SQL for the UI preference store."""

from __future__ import annotations

SELECT_PREFERENCES = """
SELECT key, value, updated_at FROM user_preferences ORDER BY key
"""

UPSERT_PREFERENCE = """
INSERT INTO user_preferences (key, value, updated_at)
VALUES (%(key)s, %(value)s, CURRENT_TIMESTAMP)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
RETURNING key, value, updated_at
"""

DELETE_PREFERENCE = """
DELETE FROM user_preferences WHERE key = %(key)s
"""
