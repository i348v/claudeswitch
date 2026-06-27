import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / ".claude_client" / "conversations.db"


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            mode TEXT,
            model TEXT,
            created_at TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
    """)
    con.commit()
    con.close()


def _conn():
    return sqlite3.connect(DB_PATH)


def create_conversation(title="New Conversation"):
    conv_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    con = _conn()
    con.execute("INSERT INTO conversations VALUES (?,?,?,?)", (conv_id, title, now, now))
    con.commit()
    con.close()
    return conv_id


def add_message(conv_id, role, content, mode, model=""):
    now = datetime.now().isoformat()
    con = _conn()
    con.execute(
        "INSERT INTO messages (conversation_id,role,content,mode,model,created_at) VALUES (?,?,?,?,?,?)",
        (conv_id, role, content, mode, model, now),
    )
    con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
    con.commit()
    con.close()


def get_messages(conv_id):
    con = _conn()
    rows = con.execute(
        "SELECT role,content,mode,model,created_at FROM messages WHERE conversation_id=? ORDER BY created_at",
        (conv_id,),
    ).fetchall()
    con.close()
    return [{"role": r[0], "content": r[1], "mode": r[2], "model": r[3], "created_at": r[4]} for r in rows]


def get_conversations():
    con = _conn()
    rows = con.execute(
        "SELECT id,title,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 60"
    ).fetchall()
    con.close()
    return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]


def update_title(conv_id, title):
    con = _conn()
    con.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
    con.commit()
    con.close()


def delete_conversation(conv_id):
    con = _conn()
    con.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    con.commit()
    con.close()
