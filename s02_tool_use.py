import os
import subprocess
import anthropic
from pathlib import Path
from dotenv import load_dotenv

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
]


def agent_loop(messages:list):
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
        for block in response.content:
            if block.type =='tool_use':
                handler_name = block.name
                parms = ', '.join(f"{k}={repr(v[:50]+('...'if len(v)>50 else '')) }" for k, v in block.input.items())
                print(f"agent: {handler_name}({parms})")
                handler = TOOL_HANDLERS.get(handler_name)
                output = handler(**block.input) if handler else f"Error: Unknown tool {handler_name}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            
        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    
    context = []

    while True:
        query = input('\n >> ')
        
        if query.lower() in ['exit', 'quit']:
            break
        
        context.append({'role': 'user', 'content': [{"type": "text", "text": query }]})
        
        agent_loop(context)
        
        for block in context[-1]['content']:
            if block.type == 'text':
                print(f"agent: {block.text}")
                
                
"""
$ python s02_tool_use.py

 >> 阅读当前项目代码，编写README.md
 
agent: bash(command='ls -la')
agent: read_file(path='D:\\Projects\\learn-claude-code\\.env')
agent: read_file(path='D:\\Projects\\learn-claude-code\\s00.openai-test.py')
agent: read_file(path='D:\\Projects\\learn-claude-code\\s01.agent_loop.py')
agent: read_file(path='D:\\Projects\\learn-claude-code\\s02_tool_use.py')
agent: read_file(path='D:\\Projects\\learn-claude-code\\s00.anthropic-test.p...')
agent: read_file(path='D:\\Projects\\learn-claude-code\\s00.ollama-test.py')
agent: write_file(path='D:\\Projects\\learn-claude-code\\README.md', content='# Learn Claude Code\n\n学习 Claude Code 风格的 AI 编码助手项目，...')
agent: bash(command='cat README.md')
agent: README.md 已创建完成。

 >>

"""