import sys
import os

# 支持直接运行 __main__.py（python __main__.py）以及模块方式（python -m cli）
if __package__ in (None, ""):
    # 直接运行时，把父目录加入路径，改用绝对导入
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from cli.main import main
else:
    from .main import main

if __name__ == "__main__":
    main()
2
2