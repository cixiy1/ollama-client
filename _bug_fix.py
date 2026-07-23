import sys, os, re
sys.path.insert(0, r'D:\it\project\Yuki-code')

with open(r'D:\it\project\Yuki-code\cli\session.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the bug: VALUES ... "", model, time.time() in compact_messages
# The model variable is not defined in this method
bug_pattern = r'("VALUES \(\?,,\?,\?,\?,\?,\?,\?\)",\s*)"(str\(uuid\.uuid4\(\)\)\[:12\], session_id, "system", summary, "",) model(, time\.time\(\)\),)'

match = re.search(bug_pattern, content)
if match:
    print("Found bug! Fixing...")
    fixed = match.group(1) + match.group(2).replace('model', '""') + match.group(4)
    content = content[:match.start()] + fixed + content[match.end():]
    with open(r'D:\it\project\Yuki-code\cli\session.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed and saved!")
else:
    # Check if it's already fixed
    idx = content.find('compact_messages')
    seg = content[idx:idx+600] if idx >= 0 else ""
    # Find the VALUES line with uuid and model
    model_lines = [l.strip() for l in seg.split('\n') if 'model' in l.lower() and 'uuid' in l.lower()]
    if model_lines:
        print(f"Still has bug: {model_lines}")
    else:
        print("Bug already fixed or pattern different")
        # Show the VALUES context
        for i, line in enumerate(seg.split('\n')[:25]):
            if 'VALUES' in line or 'uuid' in line or ('model' in line.lower() and 'time' in line):
                print(f"  {i}: {line}")
