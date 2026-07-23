"""会话持久化管理 — 对话历史存储与恢复"""
from __future__ import annotations

import sqlite3
import json
import uuid
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from cli.compress import ContextCompressor


# ---- 工具函数 ----

def _sanitize(text: str) -> str:
    """清除字符串中的孤立代理对（surrogate），避免 SQLite/UTF-8 写入崩溃。
    典型来源：终端 GBK 乱码、不完整的 emoji 字节。"""
    if not text:
        return text
    return text.encode("utf-8", "replace").decode("utf-8", "replace")


# ---- 数据模型 ----

@dataclass
class Message:
    """单条消息"""
    role: str           # "user" | "assistant" | "system"
    content: str
    thinking: str = ""  # 推理内容（如果有）
    model: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "thinking": self.thinking,
            "model": self.model,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "Message":
        return Message(
            role=d["role"],
            content=d["content"],
            thinking=d.get("thinking", ""),
            model=d.get("model", ""),
            timestamp=d.get("timestamp", time.time()),
        )


@dataclass
class Session:
    """会话"""
    id: str
    title: str
    provider: str           # Provider key
    model: str
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "provider": self.provider,
            "model": self.model,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "Session":
        return Session(
            id=d["id"],
            title=d["title"],
            provider=d.get("provider", ""),
            model=d.get("model", ""),
            messages=[Message.from_dict(m) for m in d.get("messages", [])],
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


# ---- Store ----

class SessionStore:
    """
    SQLite 会话存储。

    对话历史持久化，支持按 Provider / 模型分组，
    自动生成标题（从首条用户消息截取）。

    与 YukiAPI 完全解耦，任何 Provider 都可以用。
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = self._default_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @staticmethod
    def _default_path() -> Path:
        base = Path.home() / ".yuki-code"
        return base / "sessions.db"

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL DEFAULT '新对话',
                    provider    TEXT NOT NULL DEFAULT '',
                    model       TEXT NOT NULL DEFAULT '',
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL DEFAULT '',
                    thinking    TEXT NOT NULL DEFAULT '',
                    model       TEXT NOT NULL DEFAULT '',
                    timestamp   REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                        ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, timestamp)
            """)
            conn.execute("PRAGMA foreign_keys = ON")

    # ---- CRUD ----

    def create_session(self, provider: str = "", model: str = "",
                       title: str | None = None) -> Session:
        """新建会话"""
        sid = str(uuid.uuid4())[:8]
        now = time.time()
        if title is None:
            title = "新对话"
        session = Session(
            id=sid,
            title=title,
            provider=provider,
            model=model,
            created_at=now,
            updated_at=now,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (id,title,provider,model,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (sid, title, provider, model, now, now),
            )
        return session

    def save_session(self, session: Session):
        """保存会话元信息（不含 messages）"""
        session.updated_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET title=?,provider=?,model=?,updated_at=? WHERE id=?",
                (session.title, session.provider, session.model,
                 session.updated_at, session.id),
            )

    def add_message(self, session_id: str, message: Message):
        """追加消息到会话"""
        mid = str(uuid.uuid4())[:12]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (id,session_id,role,content,thinking,model,timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (mid, session_id, message.role, _sanitize(message.content),
                 _sanitize(message.thinking), message.model, message.timestamp),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (time.time(), session_id),
            )

    def update_last_message_thinking(self, session_id: str, thinking: str):
        """更新最后一条 assistant 消息的 thinking（流式写入时攒批）"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM messages WHERE session_id=? AND role='assistant' "
                "ORDER BY timestamp DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE messages SET thinking=? WHERE id=?",
                    (thinking, row[0]),
                )

    def get_session(self, session_id: str) -> Session | None:
        """读取单个会话（含消息）"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id,title,provider,model,created_at,updated_at "
                "FROM sessions WHERE id=?", (session_id,),
            ).fetchone()
            if not row:
                return None
            msgs = conn.execute(
                "SELECT role,content,thinking,model,timestamp "
                "FROM messages WHERE session_id=? ORDER BY timestamp",
                (session_id,),
            ).fetchall()
        return Session(
            id=row[0],
            title=row[1],
            provider=row[2],
            model=row[3],
            created_at=row[4],
            updated_at=row[5],
            messages=[
                Message(role=r, content=c, thinking=t, model=m, timestamp=ts)
                for r, c, t, m, ts in msgs
            ],
        )

    def list_sessions(self, limit: int = 20,
                      provider: str | None = None) -> list[Session]:
        """列出最近会话"""
        with sqlite3.connect(self.db_path) as conn:
            if provider:
                rows = conn.execute(
                    "SELECT id,title,provider,model,created_at,updated_at "
                    "FROM sessions WHERE provider=? ORDER BY updated_at DESC LIMIT ?",
                    (provider, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id,title,provider,model,created_at,updated_at "
                    "FROM sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            Session(id=r[0], title=r[1], provider=r[2], model=r[3],
                    created_at=r[4], updated_at=r[5])
            for r in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        """删除会话（级联删除 messages）"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE id=?", (session_id,))
            return cur.rowcount > 0

    def rename_session(self, session_id: str, title: str) -> bool:
        """重命名会话"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE sessions SET title=?,updated_at=? WHERE id=?",
                (title, time.time(), session_id),
            )
            return cur.rowcount > 0

    # ---- 生成标题 ----

    def generate_title_from_first_message(self, session: Session) -> str:
        """从第一条用户消息自动生成标题（截取前 40 字）"""
        for msg in session.messages:
            if msg.role == "user":
                text = msg.content.replace("\n", " ").strip()
                return text[:40] + ("..." if len(text) > 40 else "")
        return "新对话"

    def auto_title(self, session_id: str):
        """自动为会话生成标题"""
        session = self.get_session(session_id)
        if session and session.title == "新对话":
            title = self.generate_title_from_first_message(session)
            self.rename_session(session_id, title)

    # ---- 用量统计 ----

    def add_usage(self, session_id: str, input_tokens: int,
                  output_tokens: int, model: str):
        """记录 Token 用量"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (id,session_id,role,content,thinking,model,timestamp) "
                "VALUES (?,?,'usage',?,?,?,?)",
                (str(uuid.uuid4())[:12], session_id,
                 json.dumps({"input_tokens": input_tokens,
                              "output_tokens": output_tokens,
                              "model": model}),
                 "", model, time.time()),
            )

    def get_usage_summary(self, session_id: str) -> dict:
        """获取会话 Token 用量汇总"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT content FROM messages WHERE session_id=? AND role='usage'",
                (session_id,),
            ).fetchall()
        total_in = total_out = 0
        for (body,) in rows:
            try:
                d = json.loads(body)
                total_in += d.get("input_tokens", 0)
                total_out += d.get("output_tokens", 0)
            except Exception:
                pass
        return {"input_tokens": total_in, "output_tokens": total_out,
                "total": total_in + total_out}

    def undo_last_pair(self, session_id: str) -> bool:
        """撤销最后一对 user+assistant 消息（保留 system）"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, role, timestamp FROM messages WHERE session_id=? "
                "AND role IN ('user', 'assistant') ORDER BY timestamp DESC LIMIT 2",
                (session_id,),
            ).fetchall()
            if len(cur) < 2:
                return False
            ids = [row[0] for row in cur]
            conn.execute(
                "DELETE FROM messages WHERE id=? OR id=?",
                (ids[0], ids[1]),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (time.time(), session_id),
            )
        return True

    def compact_messages(self, session_id: str, keep_last: int = 3,
                         compressor: ContextCompressor | None = None) -> int:
        """紧凑对话历史：使用 ContextCompressor 将旧消息压缩为摘要
        保留最近 N 条（自动保护 tool pair 不被拆散）。
        返回被删除的消息数量。"""
        session = self.get_session(session_id)
        if not session or len(session.messages) <= keep_last:
            return 0

        msgs = session.messages

        if compressor is not None:
            from cli.compress import ContextCompressor as CC
            comp = compressor
        else:
            # 不知道 keep_last 是手动还是自动，创建临时压缩器
            from cli.compress import ContextCompressor, CompressConfig
            comp = ContextCompressor(CompressConfig(
                manual_compact_keep_recent=keep_last,
                auto_compact_keep_recent=keep_last,
            ))

        result = comp.compact(msgs, keep_recent=keep_last, reason="manual")

        if not result.compressed:
            return 0

        # 将保留的消息写入数据库
        with sqlite3.connect(self.db_path) as conn:
            # 1. 删除该 session 所有旧消息
            conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            # 2. 写入压缩后的消息列表
            for msg in result.kept_messages:
                mid = str(uuid.uuid4())[:12]
                conn.execute(
                    "INSERT INTO messages (id,session_id,role,content,thinking,model,timestamp) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (mid, session_id, msg.role, _sanitize(msg.content),
                     _sanitize(msg.thinking), msg.model, msg.timestamp),
                )
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (time.time(), session_id),
            )
        return result.deleted_count

    def auto_compact(self, session_id: str) -> int:
        """自动压缩：检查是否需要压缩，是则执行。返回删除的消息数。"""
        from cli.compress import ContextCompressor
        comp = ContextCompressor()
        session = self.get_session(session_id)
        if not session:
            return 0
        if not comp.should_auto_compact(session.messages):
            return 0
        return self.compact_messages(
            session_id,
            keep_last=comp.config.auto_compact_keep_recent,
            compressor=comp,
        )
