"""Yuki Code Integration Test"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, '.')

print("Yuki Code Integration Test")
print("=" * 40)

# Test 1: Core modules
print("\n[1] Testing core modules...")
from cli.main import main, interactive, console
from cli.config import load, get_current
from cli.api import YukiAPI, Provider
from cli.session import SessionStore
from cli.tools import ToolRegistry
from cli.usage import UsageStore
print("OK - All core modules imported")

# Test 2: New modules
print("\n[2] Testing new modules...")
from cli.config_manager import ConfigManager
from cli.theme import ThemeManager
from cli.shortcuts import KeyboardManager
from cli.autocomplete import CompletionEngine
from cli.multi_agent import AgentOrchestrator
from cli.agent_communication import CommunicationSystem
print("OK - All new modules imported")

# Test 3: Instantiation
print("\n[3] Testing instantiation...")
cm = ConfigManager()
tm = ThemeManager()
km = KeyboardManager()
ce = CompletionEngine()
ao = AgentOrchestrator()
cs = CommunicationSystem()
print("OK - All classes instantiated")

# Test 4: Functionality
print("\n[4] Testing functionality...")
config = load()
print(f"OK - Config loaded: {len(config.providers)} providers")

registry = ToolRegistry()
tools = registry.tool_infos()
print(f"OK - Tool registry: {len(tools)} tools")

store = SessionStore()
sessions = store.list_sessions(limit=3)
print(f"OK - Session store: {len(sessions)} sessions")

print("\n" + "=" * 40)
print("All tests passed!")
