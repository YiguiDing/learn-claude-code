import os
import re
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
SKILLS_DIR = WORKSPACE / "skills"
MODEL = "qwen3.5-plus"
MAX_TOKENS = 8000
THINKING = { "type": "enabled", "budget_tokens": 8000 }
MAIN_SYSTEM = f'You are a coding agent at { WORKSPACE }. Use bash to solve tasks. Act, don\'t explain.'
CHILD_SYSTEM = f"You are a coding subagent at { WORKSPACE }. Complete the given task, then summarize your findings."


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        """Parse YAML frontmatter between --- delimiters."""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body returned in tool_result."""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"

SKILL_LOADER = SkillLoader(SKILLS_DIR)

SKILL_PROMPT = f"""
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}
"""

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

def create_todo_handler():
    todo = TodoManager()
    return { "todo": lambda **kw: todo.update(kw["items"]) }


def safe_path(path: str) -> Path:
    path = (WORKSPACE / path).resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError(f"Path escapes workspace: {path}")
    return path

def run_bash(command:str):
    try:
        process = subprocess.run(command, shell=True, cwd=os.getcwd(), capture_output=True, text=True, encoding='utf-8', timeout=100)
        result= []
        if process.stdout:
            result.append(f"stdout: \n{process.stdout}")
        if process.stderr:
            result.append(f"stderr: \n{process.stderr}")
        return "\n".join(result).strip()[:50000]
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


def agent_loop(messages:list,SYSTEM=str,TOOLS=list,TOOL_HANDLERS=dict,is_subagent=False):
    agent_name = 'subagent' if is_subagent else 'agent'
    rounds_since_todo = 0
    while True:
        response = client.messages.create(
            model=MODEL, thinking=THINKING, max_tokens=MAX_TOKENS, 
            system=SYSTEM, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content })

        if response.stop_reason != "tool_use":
            break
        
        results = []
        used_todo = False
        for block in response.content:
            if block.type =='tool_use':
                handler_name = block.name
                parms = ', '.join(f"{k}={repr(str(v)[:50]+('...'if len(str(v))>50 else '')) }" for k, v in block.input.items())
                print(f"{agent_name}: {handler_name}({parms})")
                handler = TOOL_HANDLERS.get(handler_name)
                output = handler(**block.input) if handler else f"Error: Unknown tool {handler_name}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                if block.name == "todo":
                    used_todo = True
        
        rounds_since_todo = 0 if used_todo else rounds_since_todo+1
            
        if rounds_since_todo > 3:
            results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})   

        messages.append({"role": "user", "content": results})
    

CHILD_TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),
}

CHILD_TOOLS = [
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
    {"name": "load_skill", "description": "Load specialized knowledge by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Skill name to load"}}, "required": ["name"]}},
]

def run_subagent(prompt: str):
    context = []
    context.append({'role': 'user', 'content': [{"type": "text", "text": prompt }]})
    TODO_HANDLER = create_todo_handler()
    agent_loop(
        context, 
        SYSTEM=CHILD_SYSTEM+SKILL_PROMPT, 
        TOOLS=CHILD_TOOLS, 
        TOOL_HANDLERS=CHILD_TOOL_HANDLERS | TODO_HANDLER,
        is_subagent=True
    )
    return context[-1]['content']
    
PARENT_TOOL_HANDLERS = {
    "task": lambda **kw: run_subagent(kw["prompt"]),
}

PARENT_TOOLS = [
    {"name": "task", "description": "Spawn a subagent with fresh context.",
    "input_schema": { "type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"] }},
]

MAIN_TOOL_HANDLERS = CHILD_TOOL_HANDLERS | PARENT_TOOL_HANDLERS

MAIN_TOOLS = CHILD_TOOLS + PARENT_TOOLS

if __name__ == "__main__":
    
    context = []
    TODO_HANDLER = create_todo_handler()

    while True:
        query = input('\n >> ')
        
        if query.lower() in ['exit', 'quit']:
            break
        
        context.append({'role': 'user', 'content': [{"type": "text", "text": query }]})
        
        agent_loop(messages=context,
                   SYSTEM=MAIN_SYSTEM+SKILL_PROMPT,
                   TOOLS=MAIN_TOOLS,
                   TOOL_HANDLERS=MAIN_TOOL_HANDLERS | TODO_HANDLER
        )
        
        print(f"agent: ")
        for block in context[-1]['content']:
            if block.type == 'text':
                print(f"{block.text}")

"""
$ python s05.skill_loading.py 

 >> 总结下当前目录下的pdf文件内容
agent: bash(command='ls -la /mnt/d/Projects/learn-claude-code/*.pdf 2>/...')
agent: load_skill(name='pdf')
agent: bash(command='pdftotext /mnt/d/Projects/learn-claude-code/demo.p...')
agent: bash(command='pdftotext /mnt/d/Projects/learn-claude-code/demo.p...')
agent: 
## PDF 文件内容总结

**文件**: `demo.pdf`

**论文标题**: 基于无滤波器方波信号注入的永磁同步电机初始位置检测方法

**发表信息**:
- 期刊：电工技术学报 (TRANSACTIONS OF CHINA ELECTROTECHNICAL SOCIETY)
- 时间：2017 年 7 月，第 32 卷第 13 期
- 作者：张国强、王高林、徐殿国（哈尔滨工业大学电气工程及自动化学院）
- DOI: 10.19595/j.cnki.1000-6753.tces.L70030

---

### 研究背景
针对无位置传感器内置式永磁同步电机（IPMSM）初始位置检测，传统方法存在以下问题：
- 短脉冲电压注入法：难以确定脉冲宽度和幅值，实现困难
- 二次谐波分量法：信噪比低

### 提出的方法
一种**基于无滤波器方波信号注入**的 IPMSM 初始位置检测方法，包含两个步骤：

1. **磁极位置辨识**：向观测的转子 d 轴注入高频方波电压信号，采用无滤波器载波信号分离方法解耦位置误差信息，通过位置跟踪器获取磁极位置初定值

2. **磁极极性辨识**：基于磁饱和效应，通过施加方向相反的 d 轴电流偏置给定，比较 d 轴高频电流响应幅值大小实现磁极极性辨识

### 实验验证
- 平台：2.2kW IPMSM 矢量控制系统
- 控制芯片：STM32F103VCT6 ARM

### 主要结果
- 收敛速度快（整个初始位置辨识过程耗时 50ms）
- 可在转子**静止**或**自由运行**状态实现初始位置辨识
- 可实现低速可靠运行
- **位置观测误差最大值为 6.9°**

### 关键词
内置式永磁同步电机、无位置传感器、无滤波器、方波注入、初始位置检测

 >>
"""