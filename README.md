# Yuki Code

本地 AI 代码助手，支持多 Provider 自由配置，可连接本地 Ollama、OpenAI 兼容接口（Groq、Fireworks 等）或完全自定义的 API 端点。

基于 [`rich`](https://pypi.org/project/rich/) 与 [`requests`](https://pypi.org/project/requests/) 实现，无重型依赖，支持交互式终端界面、命令行（CLI）两种使用方式，也可作为 Python 库直接调用。

---

## 功能特性

- **多 Provider** — 支持 Ollama（本地模型）、OpenAI 兼容接口（Gorq、Fireworks 等）、自定义端点，配置后自由切换
- **推理模型兼容** — 同时兼容独立 `thinking` 字段（如 `qwen3`）与 `<think>` 内嵌标签（如 `deepseek-r1`）
- **流式对话** — 实时流式输出，推理与回答分别渲染，`Ctrl+C` 可中断
- **交互式终端界面** — 序号菜单，无需记命令
- **模型管理** — 列出 / 查看详情 / 拉取 / 删除本地模型（仅 Ollama Provider）

---

## 安装

需要 Python 3.10+。

```bash
# 克隆并安装（可编辑模式）
git clone https://github.com/cixiy1/Yuki-code.git
cd Yuki-code
pip install -e .
```

---

## 快速开始

```bash
# 启动交互式界面（默认使用本地 Ollama）
yuki

# 或直接运行入口
python -m cli
```

首次运行自动检测本地 Ollama（`http://localhost:11434`），如需连接其他 Provider：

```bash
# 添加 OpenAI 兼容 Provider
yuki config add --name groq --type openai \
    --url https://api.groq.com/openai/v1 \
    --api-key your-api-key \
    --default-model llama-3.3-70b-versatile

# 切换到该 Provider
yuki config use groq

# 指定运行（不保存）
yuki --provider groq chat llama-3.3-70b-versatile
```

---

## 命令行

```bash
# 基本命令（使用当前 Provider）
yuki status                    # 查看当前 Provider 状态
yuki list                      # 列出可用模型
yuki chat qwen3:8b             # 交互式对话
yuki generate qwen3:8b -p "解释量子纠缠"   # 单次生成

# Ollama 专属
yuki pull llama3:8b            # 拉取模型
yuki info llama3:8b            # 查看模型详情
yuki delete llama3:8b          # 删除模型
yuki running                   # 查看已加载模型

# 直接指定 Provider（临时）
yuki --url https://api.example.com chat gpt-4o --api-key sk-xxx
```

## Provider 管理

```bash
yuki config list                # 列出所有 Provider
yuki config add --name xxx --type ollama --url http://localhost:11434
yuki config remove --name xxx
yuki config rename --old xxx --new yyy
```

Provider 类型：
- `ollama` — 本地模型，支持模型管理、pull/delete、thinking
- `openai` — OpenAI 兼容端点（Groq、Fireworks 等），用 `/v1/chat/completions`
- `custom` — 完全自定义 URL，默认为 OpenAI 请求格式

---

## 作为库调用

```python
from cli.api import YukiAPI
from cli.config import load, get_current

# 使用当前激活的 Provider
provider = get_current()
api = YukiAPI(provider)

# 直接指定
from cli.config import Provider
prov = Provider(type="openai", name="Groq", base_url="https://api.groq.com/openai/v1",
               api_key="your-key", default_model="llama-3.3-70b-versatile")
api = YukiAPI(prov)

# 流式对话
for kind, text in api.chat("llama-3.3-70b-versatile",
                            [{"role": "user", "content": "你好"}],
                            stream=True):
    if kind == "thinking":
        print(f"[思考] {text}", end="", flush=True)
    else:
        print(text, end="", flush=True)
```

`YukiAPI` 主要方法：

| 方法 | 说明 |
|------|------|
| `ping()` | 检测服务是否在线 |
| `list_models()` | 列出可用模型 |
| `show_model_info(name)` | 查看模型详情（仅 Ollama） |
| `pull_model(name)` | 拉取模型（流式，仅 Ollama） |
| `delete_model(name)` | 删除模型（仅 Ollama） |
| `running_models()` | 当前已加载模型（仅 Ollama） |
| `chat(model, messages, ...)` | 对话生成，流式返回 `(kind, text)` |
| `generate(model, prompt, ...)` | 单次生成，流式返回 `(kind, text)` |

流式返回 `(kind, text)` 元组，`kind` 为 `"thinking"` 或 `"content"`。

---

## 项目结构

```
yuki-code/
├── cli/
│   ├── __init__.py      # 包元信息
│   ├── __main__.py      # 入口（python -m cli）
│   ├── api.py           # 多 Provider API 调用层
│   ├── config.py        # Provider 配置管理
│   └── main.py          # 交互式菜单 + CLI
├── pyproject.toml
├── requirements.txt
└── README.md
```

配置文件位于 `~/.yuki-code/config.json`。

---

## 开发

```bash
pip install -e .
python -m cli
```

---

## 许可证

[MIT License](LICENSE)
