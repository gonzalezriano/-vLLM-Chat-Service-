from datetime import datetime
from db import get_db


def save_message(user_id: int, role: str, content: str) -> None:
    """Persist a single chat message associated with a user."""
    conn = get_db()
    conn.execute(
        "INSERT INTO chat_messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_chat_history(user_id: int) -> list:
    """Return all messages for a user in chronological order."""
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
