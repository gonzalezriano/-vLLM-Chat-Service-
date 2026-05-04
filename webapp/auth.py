import hashlib
import secrets
from datetime import datetime, timedelta
from db import get_db, pwd_context


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_user(email: str, password: str):
    """Return user dict if credentials are valid, otherwise None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    if not pwd_context.verify(password, row["password_hash"]):
        return None
    return dict(row)


def create_session(user_id: int) -> str:
    """Create a new session and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (user_id, session_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (user_id, token_hash, expires, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def get_user_from_session(token: str):
    """Return user dict if session is valid and not expired, otherwise None."""
    token_hash = hash_token(token)
    conn = get_db()
    row = conn.execute(
        """
        SELECT users.* FROM users
        JOIN sessions ON sessions.user_id = users.id
        WHERE sessions.session_hash = ?
          AND sessions.revoked_at IS NULL
          AND sessions.expires_at > ?
        """,
        (token_hash, datetime.utcnow().isoformat()),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def revoke_session(token: str) -> None:
    """Mark a session as revoked so it cannot be used again."""
    token_hash = hash_token(token)
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE session_hash = ?",
        (datetime.utcnow().isoformat(), token_hash),
    )
    conn.commit()
    conn.close()
