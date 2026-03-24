# Learn Claude Code

学习 Claude Code 风格的 AI 编码助手项目，通过渐进式示例展示如何构建支持工具调用的 Agent 系统。

## 项目结构

```
.
├── .env                        # 环境变量配置（DASHSCOPE_API_KEY）
├── .transcripts/               # 自动保存的对话历史
├── skills/                     # 技能模块目录
│   ├── code-review/            # 代码审查技能
│   ├── mcp-builder/            # MCP 服务器构建技能
│   └── pdf/                    # PDF 处理技能
├── s00.anthropic-test.py       # Anthropic API 基础对话测试
├── s00.ollama-test.py          # Ollama 本地模型对话测试
├── s00.openai-test.py          # OpenAI 兼容接口对话测试
├── s01.agent_loop.py           # 基础 Agent 循环（支持 bash 工具）
├── s02_tool_use.py             # 多工具支持（文件操作 + bash）
├── s03.todo_write.py           # Todo 任务管理
├── s04.subagent.py             # 子代理分派
├── s05.skill_loading.py        # 技能加载系统
└── s06.context_compact.py      # 上下文压缩（微压缩 + 自动压缩）
```

## 环境配置

1. 安装依赖：
```bash
pip install anthropic python-dotenv
```

2. 配置环境变量：
创建 `.env` 文件并设置 API Key：
```
DASHSCOPE_API_KEY=your_api_key_here
```

## 示例说明

### 渐进式示例

| 文件 | 功能 | 新增工具 |
|------|------|---------|
| `s00.*.py` | 基础对话测试 | 无 |
| `s01.agent_loop.py` | 基础 Agent 循环 | `bash` |
| `s02_tool_use.py` | 多工具支持 | `bash`, `read_file`, `write_file`, `edit_file` |
| `s03.todo_write.py` | Todo 任务管理 | + `todo` |
| `s04.subagent.py` | 子代理分派 | + `task` |
| `s05.skill_loading.py` | 技能加载系统 | + `load_skill` |
| `s06.context_compact.py` | 上下文压缩 | + `compact` |

### s00 - 基础对话测试

三个文件分别测试不同的 LLM 接口：

- **openai-test.py**: 使用 OpenAI 兼容接口（DashScope）
- **anthropic-test.py**: 使用 Anthropic Messages API
- **ollama-test.py**: 使用本地 Ollama 服务

### s01 - Agent 循环

实现支持 bash 工具调用的基础 Agent：
- 使用 Anthropic Messages API
- 支持 `bash` 工具执行命令
- 循环处理工具调用直到完成任务

### s02 - 多工具支持

扩展工具集，支持文件操作：
- `bash`: 执行 shell 命令
- `read_file`: 读取文件内容
- `write_file`: 写入文件
- `edit_file`: 编辑文件（文本替换）
- 实现路径安全检查（限制在工作目录内）

### s03 - Todo 任务管理

添加任务跟踪功能：
- `TodoManager` 类管理任务列表
- 状态：`pending` → `in_progress` → `completed`
- 强制规则：同时只能有一个任务处于 `in_progress`
- 超过 3 轮未更新 todo 时自动提醒

### s04 - 子代理分派

实现主代理 - 子代理架构：
- `task` 工具：Spawn 子代理处理特定任务
- 子代理拥有独立上下文
- 支持任务委派和并行处理

### s05 - 技能加载系统

动态加载专业化知识：
- `skills/` 目录存放技能模块（SKILL.md）
- `load_skill` 工具：按需加载技能内容
- 技能包含元数据（name, description, tags）和正文
- 已内置技能：
  - `code-review`: 代码审查清单和方法
  - `mcp-builder`: MCP 服务器构建指南
  - `pdf`: PDF 文件处理流程

### s06 - 上下文压缩

解决长对话上下文超限问题：
- **微压缩 (micro_compact)**: 将旧的工具结果替换为占位符 `[Previous: used tool_name]`，保留最近 10 条
- **自动压缩 (auto_compact)**: 当 token 数超过阈值时，保存完整记录到 `.transcripts/`，并用 LLM 生成的摘要替换上下文
- **手动压缩 (compact)**: 用户可主动触发压缩

## 运行示例

```bash
# 运行基础对话测试
python s00.anthropic-test.py

# 运行 Agent（支持工具调用）
python s01.agent_loop.py
python s02_tool_use.py
python s03.todo_write.py
python s04.subagent.py
python s05.skill_loading.py
python s06.context_compact.py
```

## 核心技术点

1. **Tool Use**: 通过 Anthropic Messages API 的工具调用功能，让 LLM 能够执行外部操作
2. **Agent Loop**: 循环处理 用户输入 → LLM 响应 → 工具执行 → 结果反馈
3. **Thinking**: 启用模型的思考过程，提升复杂任务的处理能力
4. **安全限制**: 文件操作限制在工作目录内，防止路径逃逸
5. **状态管理**: TodoManager 实现任务进度跟踪
6. **代理分层**: 主代理 + 子代理架构支持任务委派
7. **知识扩展**: 技能系统支持动态加载领域知识
8. **上下文管理**: 微压缩 + 自动压缩解决 token 限制

## 使用的模型

- **qwen3.5-plus**: 通过 DashScope 提供，兼容 Anthropic API 格式

## 参考

- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [DashScope](https://dashscope.aliyun.com/)
