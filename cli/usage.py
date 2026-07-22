"""Token 用量跟踪 — 记录每次请求的输入/输出 Token 数"""
from __future__ import annotations

import sqlite3
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class UsageRecord:
    """单次请求的用量记录"""
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int = field(init=False)
    cost: float = 0.0          # 估算费用（美元）
    latency_ms: int = 0
    finish_reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        self.total_tokens = self.input_tokens + self.output_tokens


# ---- 模型单价表（参考 OpenCode，支持主流模型） ----
# 价格单位：USD / 1M tokens

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-3-5-sonnet":         (3.0, 15.0),
    "claude-3-5-haiku":          (0.8, 4.0),
    "claude-3-7-sonnet":         (3.0, 15.0),
    "claude-3-opus":             (15.0, 75.0),
    "claude-3-haiku":            (0.8, 4.0),
    # OpenAI
    "gpt-4o":                    (2.5, 10.0),
    "gpt-4o-mini":               (0.15, 0.6),
    "gpt-4.1":                   (2.0, 8.0),
    "gpt-4.1-mini":              (0.1, 0.4),
    "gpt-4-turbo":               (10.0, 30.0),
    "gpt-4":                     (30.0, 60.0),
    "o1":                        (15.0, 60.0),
    "o1-mini":                   (1.1, 5.5),
    "o1-preview":                (15.0, 60.0),
    "o3":                        (10.0, 40.0),
    "o3-mini":                   (1.1, 5.5),
    # Groq (超便宜)
    "llama-3.3-70b-versatile":   (0.0, 0.0),
    "llama-4-maverick":          (0.0, 0.0),
    "llama-4-scout":             (0.0, 0.0),
    "qwq-32b":                   (0.0, 0.0),
    "deepseek-r1-distill-llama": (0.0, 0.0),
    # Google Gemini
    "gemini-2.5-pro":            (1.25, 5.0),
    "gemini-2.5-flash":          (0.075, 0.3),
    "gemini-2.0-flash":          (0.1, 0.4),
    # Ollama (本地，估算免费)
    "ollama":                    (0.0, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """根据模型名称估算费用"""
    model_lower = model.lower()
    for key, (in_price, out_price) in MODEL_PRICING.items():
        if key in model_lower:
            in_cost = (input_tokens / 1_000_000) * in_price
            out_cost = (output_tokens / 1_000_000) * out_price
            return round(in_cost + out_cost, 6)
    return 0.0


# ---- 存储 ----

class UsageStore:
    """SQLite 用量存储"""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = self._default_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @staticmethod
    def _default_path() -> Path:
        return Path.home() / ".yuki-code" / "usage.db"

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider        TEXT NOT NULL,
                    model           TEXT NOT NULL,
                    input_tokens    INTEGER NOT NULL DEFAULT 0,
                    output_tokens   INTEGER NOT NULL DEFAULT 0,
                    total_tokens    INTEGER NOT NULL DEFAULT 0,
                    cost_usd        REAL NOT NULL DEFAULT 0.0,
                    latency_ms      INTEGER NOT NULL DEFAULT 0,
                    finish_reason   TEXT NOT NULL DEFAULT '',
                    timestamp       REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_model
                ON usage(model, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_provider
                ON usage(provider, timestamp)
            """)

    def record(self, record: UsageRecord):
        cost = estimate_cost(record.model,
                            record.input_tokens,
                            record.output_tokens)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO usage "
                "(provider,model,input_tokens,output_tokens,total_tokens,"
                "cost_usd,latency_ms,finish_reason,timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (record.provider, record.model,
                 record.input_tokens, record.output_tokens,
                 record.total_tokens, cost, record.latency_ms,
                 record.finish_reason, record.timestamp),
            )

    def summary(
        self,
        model: str | None = None,
        provider: str | None = None,
        days: int = 30,
    ) -> dict:
        """获取用量汇总"""
        cutoff = time.time() - days * 86400
        with sqlite3.connect(self.db_path) as conn:
            if model:
                row = conn.execute(
                    "SELECT COALESCE(SUM(input_tokens),0),"
                    "       COALESCE(SUM(output_tokens),0),"
                    "       COALESCE(SUM(total_tokens),0),"
                    "       COALESCE(SUM(cost_usd),0.0),"
                    "       COUNT(*) "
                    "FROM usage "
                    "WHERE model=? AND timestamp>=?",
                    (model, cutoff),
                ).fetchone()
            elif provider:
                row = conn.execute(
                    "SELECT COALESCE(SUM(input_tokens),0),"
                    "       COALESCE(SUM(output_tokens),0),"
                    "       COALESCE(SUM(total_tokens),0),"
                    "       COALESCE(SUM(cost_usd),0.0),"
                    "       COUNT(*) "
                    "FROM usage "
                    "WHERE provider=? AND timestamp>=?",
                    (provider, cutoff),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(input_tokens),0),"
                    "       COALESCE(SUM(output_tokens),0),"
                    "       COALESCE(SUM(total_tokens),0),"
                    "       COALESCE(SUM(cost_usd),0.0),"
                    "       COUNT(*) "
                    "FROM usage WHERE timestamp>=?",
                    (cutoff,),
                ).fetchone()
        in_t, out_t, total_t, cost, count = row
        return {
            "input_tokens": in_t,
            "output_tokens": out_t,
            "total_tokens": total_t,
            "cost_usd": round(cost, 6),
            "requests": count,
            "days": days,
        }

    def recent(self, limit: int = 10) -> list[UsageRecord]:
        """最近 N 条记录"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT provider,model,input_tokens,output_tokens,"
                "       latency_ms,finish_reason,timestamp "
                "FROM usage ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            UsageRecord(
                provider=r[0], model=r[1],
                input_tokens=r[2], output_tokens=r[3],
                latency_ms=r[4], finish_reason=r[5], timestamp=r[6],
            )
            for r in rows
        ]
