import sys
import os

# 支持直接运行 __main__.py（python __main__.py）以及模块方式（python -m ollama_client）
if __package__ in (None, ""):
    # 直接运行时，把父目录加入路径，改用绝对导入
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ollama_client.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    main()
