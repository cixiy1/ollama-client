import sys
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')

from cli.session import SessionStore
store = SessionStore()

# Find sessions with 5+ messages
sessions = store.list_sessions(limit=20)
for s in sessions:
    full = store.get_session(s.id)
    if full:
        count = len(full.messages)
        print(f"  {s.id}: {count} messages")
        if count >= 5:
            print(f"    --> Will test compact on this one!")
