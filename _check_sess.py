import sys, os
sys.path.insert(0, r'D:\it\project\Yuki-code')
sys.stdout.reconfigure(encoding='utf-8')

from cli.session import SessionStore

# Test session restoration
store = SessionStore()
sess = store.get_session('11601467')
if sess:
    print(f"Session loaded: {sess.title}")
    print(f"Messages: {len(sess.messages)}")
    for m in sess.messages:
        role = m.role.upper()
        content = m.content[:60] + ("..." if len(m.content) > 60 else "")
        print(f"  [{role}] {content}")
else:
    print("Session not found")
