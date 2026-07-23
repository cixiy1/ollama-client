"""Bug check"""
import sys
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')

print("Bug Check Report")
print("=" * 40)

# 1. Tool registry
print("\n[1] Tool Registry")
from cli.tools import ToolRegistry
registry = ToolRegistry()
tools = registry.tool_infos()
print(f"OK - {len(tools)} tools registered")
for t in tools:
    print(f"  - {t.name}")

# 2. Config
print("\n[2] Config System")
from cli.config import load
cfg = load()
print(f"OK - {len(cfg.providers)} providers: {list(cfg.providers.keys())}")

# 3. Context
print("\n[3] Context Loading")
from cli.context import discover_context_files
ctx = discover_context_files(".")
print(f"OK - {len(ctx)} context files")

# 4. API
print("\n[4] API System")
from cli.api import YukiAPI
from cli.config import get_current
prov = get_current()
if prov:
    api = YukiAPI(prov)
    print(f"OK - API: {prov.name} @ {prov.base_url}")
else:
    print("WARN - No provider")

# 5. Menu extensions import
print("\n[5] Menu Extensions")
try:
    from cli.menu_extensions import config_menu, theme_menu, shortcuts_menu, agent_menu
    print("OK - All menu functions imported")
except Exception as e:
    print(f"FAIL - {e}")

print("\n" + "=" * 40)
print("Bug check completed!")
