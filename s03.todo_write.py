import os
import subprocess
import anthropic
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, List, Any

load_dotenv()

client = anthropic.Anthropic(
    base_url="https://coding.dashscope.aliyuncs.com/apps/anthropic",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
)

WORKSPACE = Path.cwd()
MODEL = "qwen3.5-plus"
MAX_TOKENS = 8000
THINKING = { "type": "enabled", "budget_tokens": 8000 }
SYSTEM = [{"type": "text", "text": f'You are a coding agent at { WORKSPACE }. Use bash to solve tasks. Act, don\'t explain.'}]


class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: List[Dict[str, Any]]) -> str:
        validated = []
        in_progress_count = 0
        for id, item in enumerate(items, 1):
            
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(id)))
            
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            
            if status not in ["pending", "in_progress", "completed"]:
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            
            if status == "in_progress":
                in_progress_count += 1
            
            validated.append({"id": item_id, "text": text, "status": status})
            
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            mapper = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
            lines.append(f"{mapper[item["status"]]} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


def safe_path(path: str) -> Path:
    path = (WORKSPACE / path).resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError(f"Path escapes workspace: {path}")
    return path

def run_bash(command:str):
    try:
        process = subprocess.run(command, shell=True, cwd=os.getcwd(), capture_output=True, text=True, encoding='utf-8', timeout=100)
        result = (process.stdout + process.stderr).strip()
        return result[:50000]
    except Exception as e:
        return f"Error: {e}"
    
def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text(encoding='utf-8')
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding='utf-8')
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding='utf-8')
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1),encoding='utf-8')
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

# -- The dispatch map: {tool_name: handler} --
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "todo", "description": "Update task list. Track progress on multi-step tasks.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "text", "status"]}}}, "required": ["items"]}},
]


def agent_loop(messages:list):
    rounds_since_todo = 0
    while True:
        response = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM, thinking=THINKING,
            tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content })

        if response.stop_reason != "tool_use":
            return

        results = []
        used_todo = False
        for block in response.content:
            if block.type =='tool_use':
                handler_name = block.name
                parms = ', '.join(f"{k}={repr(str(v[:50])+('...'if len(v)>50 else '')) }" for k, v in block.input.items())
                print(f"agent: {handler_name}({parms})")
                handler = TOOL_HANDLERS.get(handler_name)
                output = handler(**block.input) if handler else f"Error: Unknown tool {handler_name}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                if block.name == "todo":
                    used_todo = True
        
        rounds_since_todo = 0 if used_todo else rounds_since_todo+1
            
        if rounds_since_todo > 3:
            results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})   

        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    
    context = []

    while True:
        query = input('\n >> ')
        
        if query.lower() in ['exit', 'quit']:
            break
        
        context.append({'role': 'user', 'content': [{"type": "text", "text": query }]})
        
        agent_loop(context)
        
        print(f"agent: ")
        for block in context[-1]['content']:
            if block.type == 'text':
                print(f"{block.text}")
                
                
"""
$ python s03.todo_write.py

 >> 使用todo，1.计算123x321 2.然后结果/554 3.最后再加上223
agent: todo(items="[{'id': '1', 'text': '计算123x321', 'status': 'pending'}, {'id': '2', 'text': '将结果除以554', 'status': 'pending'}, {'id': '3', 'text': '最后再加上223', 'status': 'pending'}]")
agent: todo(items="[{'id': '1', 'text': '计算123x321', 'status': 'in_progress'}, {'id': '2', 'text': '将结果除以554', 'status': 'pending'}, {'id': '3', 'text': '最后再加上223', 'status': 'pending'}]")
agent: bash(command='echo $((123 * 321))')
agent: bash(command='expr 123 \\* 321')
agent: todo(items="[{'id': '1', 'text': '计算123x321', 'status': 'completed'}, {'id': '2', 'text': '将结果除以554', 'status': 'in_progress'}, {'id': '3', 'text': '最后再加上223', 'status': 'pending'}]")
agent: bash(command='expr 39483 / 554')
agent: todo(items="[{'id': '1', 'text': '计算123x321', 'status': 'completed'}, {'id': '2', 'text': '将结果除以554', 'status': 'completed'}, {'id': '3', 'text': '最后再加上223', 'status': 'in_progress'}]")
agent: bash(command='expr 71 + 223')
agent: todo(items="[{'id': '1', 'text': '计算123x321', 'status': 'completed'}, {'id': '2', 'text': '将结果除以554', 'status': 'completed'}, {'id': '3', 'text': '最后再加上223', 'status': 'completed'}]")
agent: 

计算完成！

**结果：294**

步骤：
1. 123 × 321 = 39483
2. 39483 ÷ 554 = 71
3. 71 + 223 = 294

$ python s03.todo_write.py 

 >> 你怎么理解这个todo工具的使用？何时使用、如何使用？
agent: bash(command='ls -la')
agent: read_file(path='s03.todo_write.py')
agent: 
根据代码分析，**todo 工具**的理解如下：

## 何时使用

| 场景 | 说明 |
|------|------|
| **多步骤任务** | 任务需要 3 步以上完成时 |
| **复杂任务拆解** | 用户请求包含多个子任务时 |
| **长对话跟踪** | 防止在多次工具调用中迷失进度 |
| **超过 3 轮未更新** | 代码中有强制提醒机制 |

## 如何使用

```python
todo(items=[
    {"id": "1", "text": "任务描述 1", "status": "pending"},
    {"id": "2", "text": "任务描述 2", "status": "in_progress"},
    {"id": "3", "text": "任务描述 3", "status": "completed"}
])
```

## 核心规则

1. **状态只有 3 种**：`pending` → `in_progress` → `completed`
2. **同时只能有 1 个** `in_progress` 任务
3. **每个任务必须有** `id`、`text`、`status`
4. **任务开始时**：将第一步设为 `in_progress`
5. **每完成一步**：更新当前为 `completed`，下一步为 `in_progress`

## 输出格式

```
[ ] #1: 计算 123x321
[>] #2: 将结果除以 554
[ ] #3: 最后再加上 223

(1/3 completed)
```

## 典型工作流

```
1. 接收任务 → 创建 todo 列表（全 pending）
2. 开始执行 → 第 1 项改为 in_progress
3. 执行工具 → 完成第 1 项 → 第 1 项 completed，第 2 项 in_progress
4. 循环直到全部 completed
5. 汇总结果给用户
```

本质是**让 AI 自己跟踪任务进度**，避免在多轮工具调用中遗漏步骤。

 >>
"""
