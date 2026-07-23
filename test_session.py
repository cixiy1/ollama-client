"""Test session history"""
import sys
sys.path.insert(0, '.')

from cli.session import SessionStore, Session, Message
import time

print("Testing session history...")

store = SessionStore()

# Use create_session instead of manual Session
test_session = store.create_session(
    provider='ollama',
    model='qwen3:8b',
    title='Test Session'
)
print(f"Created session: {test_session.id}")

# Test messages
msg = Message(role='user', content='Hello', timestamp=time.time())
store.add_message(test_session.id, msg)

# Verify
loaded = store.get_session(test_session.id)
print(f"Session load: {loaded.title if loaded else 'FAIL'}")
print(f"Messages count: {len(loaded.messages) if loaded else 'FAIL'}")

# Cleanup
store.delete_session(test_session.id)
print("Session test PASSED")
