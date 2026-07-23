path = r'D:\it\project\Yuki-code\cli\tools.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = "                \"示例: git status / git diff src/main.py / git commit -m 'fix: bug'\","
if old in content:
    print('found description line!')
    content = content.replace(old, '                "示例: git status / git diff src/main.py / git commit -m fix:bug",')
else:
    print('not found, checking...')
    idx = content.find("示例: git status")
    print(repr(content[idx-5:idx+80]))

old2 = '                        "格式：子命令 [参数...]，如 \'diff --cached\' 或 \'log -n 10\'。"'
if old2 in content:
    print('found format line!')
    content = content.replace(old2, '                        "格式：子命令 [参数...]，如 diff --cached 或 log -n 10。"')
else:
    print('format line not found, checking...')
    idx = content.find("格式：子命令")
    print(repr(content[idx-5:idx+80]))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
