import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / ".claude_client" / "conversations.db"


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT,
            system_prompt TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            updated_at TEXT,
            project_id TEXT REFERENCES projects(id)
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
    # Migrations
    conv_cols = [r[1] for r in con.execute("PRAGMA table_info(conversations)").fetchall()]
    if "project_id" not in conv_cols:
        con.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT REFERENCES projects(id)")
    msg_cols = [r[1] for r in con.execute("PRAGMA table_info(messages)").fetchall()]
    if "account_label" not in msg_cols:
        con.execute("ALTER TABLE messages ADD COLUMN account_label TEXT DEFAULT ''")
    if "input_tokens" not in msg_cols:
        con.execute("ALTER TABLE messages ADD COLUMN input_tokens INTEGER DEFAULT 0")
    if "output_tokens" not in msg_cols:
        con.execute("ALTER TABLE messages ADD COLUMN output_tokens INTEGER DEFAULT 0")
    con.commit()
    con.close()


# ── Project helpers ────────────────────────────────────────────────────────────

def create_project(name: str, system_prompt: str = "") -> str:
    pid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    con = _conn()
    con.execute("INSERT INTO projects VALUES (?,?,?,?)", (pid, name, system_prompt, now))
    con.commit()
    con.close()
    return pid


def list_projects() -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT id,name,system_prompt FROM projects ORDER BY created_at").fetchall()
    con.close()
    return [{"id": r[0], "name": r[1], "system_prompt": r[2]} for r in rows]


def get_project(project_id: str) -> dict | None:
    con = _conn()
    row = con.execute("SELECT id,name,system_prompt FROM projects WHERE id=?", (project_id,)).fetchone()
    con.close()
    return {"id": row[0], "name": row[1], "system_prompt": row[2]} if row else None


def update_project(project_id: str, name: str, system_prompt: str):
    con = _conn()
    con.execute("UPDATE projects SET name=?,system_prompt=? WHERE id=?",
                (name, system_prompt, project_id))
    con.commit()
    con.close()


def delete_project(project_id: str):
    con = _conn()
    con.execute("UPDATE conversations SET project_id=NULL WHERE project_id=?", (project_id,))
    con.execute("DELETE FROM projects WHERE id=?", (project_id,))
    con.commit()
    con.close()


def set_conversation_project(conv_id: str, project_id: str | None):
    con = _conn()
    con.execute("UPDATE conversations SET project_id=? WHERE id=?", (project_id, conv_id))
    con.commit()
    con.close()


def _conn():
    return sqlite3.connect(DB_PATH)


def create_conversation(title="New Conversation", project_id: str | None = None):
    conv_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    con = _conn()
    con.execute("INSERT INTO conversations VALUES (?,?,?,?,?)",
                (conv_id, title, now, now, project_id))
    con.commit()
    con.close()
    return conv_id


def add_message(conv_id, role, content, mode, model="", account_label="",
                input_tokens=0, output_tokens=0):
    now = datetime.now().isoformat()
    con = _conn()
    con.execute(
        "INSERT INTO messages (conversation_id,role,content,mode,model,created_at,account_label,input_tokens,output_tokens)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (conv_id, role, content, mode, model, now, account_label, input_tokens, output_tokens),
    )
    con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
    con.commit()
    con.close()


def get_messages(conv_id):
    con = _conn()
    rows = con.execute(
        "SELECT role,content,mode,model,created_at,account_label FROM messages WHERE conversation_id=? ORDER BY created_at",
        (conv_id,),
    ).fetchall()
    con.close()
    return [{"role": r[0], "content": r[1], "mode": r[2], "model": r[3],
             "created_at": r[4], "account_label": r[5] if len(r) > 5 else ""} for r in rows]


def get_conversations(project_id: str | None = None):
    con = _conn()
    if project_id:
        rows = con.execute(
            "SELECT id,title,updated_at FROM conversations WHERE project_id=? ORDER BY updated_at DESC LIMIT 60",
            (project_id,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id,title,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 60"
        ).fetchall()
    con.close()
    return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]


def search_conversations(query: str, project_id: str | None = None):
    q = f"%{query}%"
    con = _conn()
    if project_id:
        rows = con.execute(
            """
            SELECT DISTINCT c.id, c.title, c.updated_at
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE (c.title LIKE ? OR m.content LIKE ?) AND c.project_id=?
            ORDER BY c.updated_at DESC LIMIT 60
            """,
            (q, q, project_id),
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT DISTINCT c.id, c.title, c.updated_at
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.title LIKE ? OR m.content LIKE ?
            ORDER BY c.updated_at DESC LIMIT 60
            """,
            (q, q),
        ).fetchall()
    con.close()
    return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]


def update_title(conv_id, title):
    con = _conn()
    con.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
    con.commit()
    con.close()


def truncate_messages(conv_id: str, keep_n: int):
    """Delete all messages after the first keep_n in a conversation."""
    con = _conn()
    rows = con.execute(
        "SELECT id FROM messages WHERE conversation_id=? ORDER BY created_at, id",
        (conv_id,),
    ).fetchall()
    if keep_n >= len(rows):
        con.close()
        return
    if keep_n == 0:
        con.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    else:
        last_keep_id = rows[keep_n - 1][0]
        con.execute(
            "DELETE FROM messages WHERE conversation_id=? AND id > ?",
            (conv_id, last_keep_id),
        )
    con.commit()
    con.close()


def delete_conversation(conv_id):
    con = _conn()
    con.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    con.commit()
    con.close()


def import_from_claudeai(path: str) -> tuple[int, int]:
    """
    Import conversations from a Claude.ai data export.
    Accepts the raw conversations.json or a .zip containing it.
    Returns (conversations_imported, messages_imported).
    """
    import json
    import zipfile
    from pathlib import Path as P

    p = P(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            target = next((n for n in names if n.endswith("conversations.json")), None)
            if not target:
                raise ValueError("No conversations.json found inside the zip.")
            with z.open(target) as f:
                data = json.load(f)
    else:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Unexpected format — expected a JSON array of conversations.")

    conv_count = 0
    msg_count  = 0
    con = _conn()

    for convo in data:
        conv_id  = convo.get("uuid", str(uuid.uuid4()))
        title    = convo.get("name") or "Imported Conversation"
        created  = convo.get("created_at", datetime.now().isoformat())
        updated  = convo.get("updated_at", created)

        # Skip duplicates
        if con.execute("SELECT 1 FROM conversations WHERE id=?", (conv_id,)).fetchone():
            continue

        con.execute("INSERT INTO conversations VALUES (?,?,?,?,?)",
                    (conv_id, title, created, updated, None))
        conv_count += 1

        for msg in convo.get("chat_messages", []):
            sender = msg.get("sender", "human")
            role   = "user" if sender == "human" else "assistant"
            text   = msg.get("text") or ""

            # Append any extracted attachment text
            for att in msg.get("attachments", []):
                extracted = att.get("extracted_content") or ""
                if extracted:
                    fname = att.get("file_name", "attachment")
                    text += f"\n\n[{fname}]\n{extracted}"

            ts = msg.get("created_at", created)
            con.execute(
                "INSERT INTO messages (conversation_id,role,content,mode,model,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (conv_id, role, text, "imported", "", ts),
            )
            msg_count += 1

    con.commit()
    con.close()
    return conv_count, msg_count
