# Ollama Client

一个轻量的 Ollama 本地模型对接工具，同时提供 **交互式终端界面** 与 **命令行（CLI）** 两种使用方式，并可作为 Python 库直接调用。

基于 [`requests`](https://pypi.org/project/requests/) 与 [`rich`](https://pypi.org/project/rich/) 实现，无重型依赖。

---

## 功能特性

- 🔌 **服务检测** — 检测本地 Ollama 服务是否在线
- 📋 **模型管理** — 列出 / 查看详情 / 拉取 / 删除本地模型
- 💬 **流式对话** — 实时流式输出，`Ctrl+C` 可中断
- 📝 **单次生成** — 一次性 prompt 生成
- 🔁 **管道模式** — 支持 shell 管道输入（适合脚本）
- 🪟 **GUI 风格渲染** — 推理模型的「思考过程」与「回答」分两张独立卡片展示，互不混排
- 🧠 **推理模型兼容** — 同时兼容独立 `thinking` 字段（如 `qwen3`）与 `<think>` 内嵌标签（如 `deepseek-r1`）
- ▶️ **查看加载** — 查看 Ollama 当前已加载到内存的模型

---

## 安装

需要 Python 3.10+ 以及已运行的 [Ollama](https://ollama.com) 服务。

```bash
# 从源码安装（可编辑模式）
git clone <your-repo-url>
cd ollama-client
pip install -e .

# 或者仅安装依赖后直接运行
pip install -r requirements.txt
```

---

## 使用方式

### 1. 交互式界面（默认）

不带任何参数运行，直接进入终端主菜单：

```bash
ollama-client            # 已安装时
python -m ollama_client  # 或直接运行入口
```

菜单中可选择：对话、查看模型、单次生成、拉取、删除等操作。

### 2. 命令行（CLI）

```bash
# 服务状态
ollama-client status

# 列出本地模型
ollama-client list

# 交互式对话（流式）
ollama-client chat qwen3:8b

# 带系统提示词
ollama-client chat qwen3:8b --system "你是一个严谨的物理老师"

# 管道模式（适合脚本）
echo "解释相对论" | ollama-client chat qwen3:8b --stdin

# 单次生成
ollama-client generate qwen3:8b --prompt "用一句话解释量子纠缠"

# 查看模型详情
ollama-client info qwen2.5-coder:7b

# 拉取新模型
ollama-client pull llama3:8b

# 删除模型
ollama-client delete deepseek-r1:1.5b

# 查看当前加载的模型
ollama-client running

# 指定 API 地址（默认 http://localhost:11434）
ollama-client --url http://192.168.1.10:11434 list
```

---

## 作为库调用

除了命令行，也可以在自己的 Python 项目中直接导入使用：

```python
from ollama_client.api import OllamaAPI

api = OllamaAPI()  # 默认 http://localhost:11434

# 检测服务
if not api.ping():
    raise RuntimeError("Ollama 服务未启动")

# 列出模型
for m in api.list_models():
    print(m.name, m.size)

# 流式生成（推理模型自动分离 thinking / content）
for kind, text in api.generate("qwen3:8b", "你好", stream=True):
    if kind == "thinking":
        print(f"[思考] {text}", end="", flush=True)
    else:
        print(text, end="", flush=True)

# 非流式一次拿结果
result = "".join(
    t for k, t in api.generate("qwen3:8b", "1+1=", stream=True) if k == "content"
)
print(result)
```

`OllamaAPI` 主要方法：

| 方法 | 说明 |
|------|------|
| `ping()` | 检测服务是否在线，返回 `bool` |
| `list_models()` | 列出本地模型，返回 `Model` 列表 |
| `show_model(name)` | 获取单个模型详情 |
| `pull_model(name)` | 拉取模型（流式进度） |
| `delete_model(name)` | 删除模型 |
| `running_models()` | 当前已加载的模型 |
| `chat(messages, ...)` | 多轮对话，流式返回 `(kind, text)` |
| `generate(prompt, ...)` | 单次生成，流式返回 `(kind, text)` |

`chat` / `generate` 的流式迭代器返回 `(kind, text)` 元组，`kind` 为 `"thinking"` 或 `"content"`，便于渲染推理过程。

---

## 项目结构

```
ollama-client/
├── pyproject.toml
├── requirements.txt
├── README.md
└── ollama_client/
    ├── __init__.py     # 包元信息 / 版本
    ├── __main__.py     # 运行入口（python -m ollama_client）
    ├── api.py          # Ollama HTTP API 封装
    └── cli.py          # 交互式菜单 + CLI 子命令
```

---

## 开发

```bash
# 安装可编辑版本
pip install -e .

# 运行测试 / 调试
python -m ollama_client
```

代码风格：纯标准库 + `requests` + `rich`，无构建框架依赖。

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。（如需其他许可证，替换 `LICENSE` 文件即可。）

---

## 贡献

欢迎提交 Issue 与 Pull Request。提交前请确保：

1. 代码可通过 `python -m ollama_client` 正常进入主菜单
2. 新增功能有基本的命令行 / 库调用示例
3. 保持对推理模型（思考 / 回答分离）的兼容
