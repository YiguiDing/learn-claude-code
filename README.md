# Learn Claude Code

学习 Claude Code 风格的 AI 编码助手项目，通过渐进式示例展示如何构建支持工具调用的 Agent 系统。

## 项目结构

```
.
├── .env                    # 环境变量配置（DASHSCOPE_API_KEY）
├── s00.anthropic-test.py   # Anthropic API 基础对话测试
├── s00.ollama-test.py      # Ollama 本地模型对话测试
├── s00.openai-test.py      # OpenAI 兼容接口对话测试
├── s01.agent_loop.py       # 基础 Agent 循环（支持 bash 工具）
└── s02_tool_use.py         # 多工具支持（文件操作 + bash）
```

## 环境配置

1. 安装依赖：
```bash
pip install anthropic python-dotenv ollama
```

2. 配置环境变量：
创建 `.env` 文件并设置 API Key：
```
DASHSCOPE_API_KEY=your_api_key_here
```

## 示例说明

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

## 运行示例

```bash
# 运行基础对话测试
python s00.anthropic-test.py

# 运行 Agent（支持工具调用）
python s01.agent_loop.py
python s02_tool_use.py
```

## 核心技术点

1. **Tool Use**: 通过 Anthropic Messages API 的工具调用功能，让 LLM 能够执行外部操作
2. **Agent Loop**: 循环处理用户输入 → LLM 响应 → 工具执行 → 结果反馈
3. **Thinking**: 启用模型的思考过程，提升复杂任务的处理能力
4. **安全限制**: 文件操作限制在工作目录内，防止路径逃逸
5. **状态管理**: 通过 TodoManager 实现持久化的任务状态

## 使用的模型

- **qwen3.5-plus**: 通过 DashScope 提供，兼容 Anthropic API 格式

## 参考

- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [DashScope](https://dashscope.aliyun.com/)
