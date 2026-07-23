"""测试上下文压缩模块"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli.compress import (
    ContextCompressor, CompressConfig, CompressResult,
    estimate_messages_tokens, find_tool_pairs, _has_tool_call,
)
from cli.session import Message

def make_msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)

# ── 1. 工具配对检测 ──
msgs = [
    make_msg("user", "帮我搜索文件"),
    make_msg("assistant", '{"role":"assistant","content":{"tool_calls":[{"name":"grep","args":{"pattern":"test"}]}}'),
    make_msg("tool", '{"matches":["file1.txt"]}'),
    make_msg("user", "继续"),
]
pairs = find_tool_pairs(msgs)
assert len(pairs) == 1, f"Expected 1 pair, got {len(pairs)}"
print(f"[OK] 工具配对: {len(pairs)} pairs")

# ── 2. Token 估算 ──
tokens = estimate_messages_tokens(msgs)
assert tokens > 0
print(f"[OK] Token 估算: {tokens}")

# ── 3. Split point: 不对分 tool pair ──
comp = ContextCompressor(CompressConfig())
idx = comp._find_split_point(msgs, keep_recent=1)
assert idx == 0 or not comp._splits_tool_pair(msgs, idx), f"Split at {idx} splits a tool pair!"
print(f"[OK] Split point: {idx}")

# ── 4. should_auto_compact ──
long_msgs = [make_msg("user", f"q{i}") for i in range(40)]
assert comp.should_auto_compact(long_msgs) == True, "Should compact 40 messages"
short_msgs = [make_msg("user", f"q{i}") for i in range(5)]
assert comp.should_auto_compact(short_msgs) == False, "Should NOT compact 5 messages"
print(f"[OK] Auto-compact detection: 40t 5f")

# ── 5. rule_summarize ──
summary = comp._rule_summarize(msgs)
assert "摘要" in summary
print(f"[OK] Rulesummarize: {len(summary)} chars")

# ── 6. compact (rule-based, no api) ──
result = comp.compact(long_msgs, keep_recent=3, reason="test")
assert result.compressed == True
assert result.deleted_count == len(long_msgs) - 3
assert len(result.kept_messages) == 4  # 1 summary + 3 kept
print(f"[OK] Compact: deleted {result.deleted_count}, kept {len(result.kept_messages)}")

# ── 7. prune_tool_results ──
big_tool = make_msg("tool", "x" * 2000)
pruned = comp.prune_tool_results([big_tool], max_content_chars=100)
assert len(pruned[0].content) < 500
print(f"[OK] Prune: {len(big_tool.content)} -> {len(pruned[0].content)} chars")

# ── 8. analyze ──
analysis = comp.analyze(msgs)
assert "total_messages" in analysis
assert "estimated_tokens" in analysis
assert "need_compact" in analysis
print(f"[OK] Analyze: {analysis['total_messages']} msgs, {analysis['estimated_tokens']} tokens")

print("\nAll 8 tests passed!")
