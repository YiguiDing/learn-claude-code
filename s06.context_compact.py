import json
import os
import re
import subprocess
import time
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
TRANSCRIPT_DIR = WORKSPACE / ".transcripts"
MODEL = "qwen3.5-plus"
MAX_TOKENS = 8000
AUTO_COMPACT_TOKEN_THRESHOLD = 50000
KEEP_RECENT = 10
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

# -- Layer 1: micro_compact - replace old tool results with placeholders --
def micro_compact(messages: list) -> list:
    # Collect (msg_index, part_index, tool_result_dict) for all tool_result entries
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))
    if len(tool_results) <= KEEP_RECENT:
        return messages
    # Find tool_name for each result by matching tool_use_id in prior assistant messages
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name
    # Clear old results (keep last KEEP_RECENT)
    to_clear = tool_results[:-KEEP_RECENT]
    for _, _, result in to_clear:
        if isinstance(result.get("content"), str) and len(result["content"]) > 100:
            tool_id = result.get("tool_use_id", "")
            tool_name = tool_name_map.get(tool_id, "unknown")
            result["content"] = f"[Previous: used {tool_name}]"
    return messages

def estimate_tokens(messages: list) -> int:
    """Rough token count: ~4 chars per token."""
    return len(str(messages)) // 4

# -- Layer 2: auto_compact - save transcript, summarize, replace messages --
def auto_compact(messages: list) -> list:
    # Save full transcript to disk
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for bl in messages:
            f.write(json.dumps(bl, default=str) + "\n")
    print(f"[transcript saved: {transcript_path}]")
    
    # Ask LLM to summarize
    conversation_text = json.dumps(messages, default=str)[:80000]
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, "
            "2) Current state, "
            "3) Key decisions made. "
            "Be concise but preserve critical details.\n\n" + 
            conversation_text}],
        max_tokens=2000,
    )

    summarys = []
    for block in response.content:
        if block.type == "text":
            summarys.append(block.text)
    summary = "\n".join(summarys)
    
    # Replace all messages with compressed summary
    return [
        {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
        {"role": "assistant", "content": "Understood. I have the context from the summary. Continuing."},
    ]

def agent_loop(messages:list,SYSTEM=str,TOOLS=list,TOOL_HANDLERS=dict,is_subagent=False):
    agent_name = 'subagent' if is_subagent else 'agent'
    rounds_since_todo = 0
    while True:
        # micro_compact before each LLM call
        micro_compact(messages) 
        
        # auto_compact if token estimate exceeds threshold
        if estimate_tokens(messages) > AUTO_COMPACT_TOKEN_THRESHOLD:
            print("[auto_compact triggered]")
            messages[:] = auto_compact(messages)
        
        response = client.messages.create(
            model=MODEL, thinking=THINKING, max_tokens=MAX_TOKENS, 
            system=SYSTEM, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content })

        if response.stop_reason != "tool_use":
            break
        
        results = []
        used_todo = False
        manual_compact = False
        for block in response.content:
            if block.type =='tool_use':
                if block.name == "compact":
                    manual_compact = True
                    output = "Compressing..."
                else:
                    if block.name == "todo":
                        used_todo = True
                    handler_name = block.name
                    parms = ', '.join(f"{k}={repr(str(v)[:50]+('...'if len(str(v))>50 else '')) }" for k, v in block.input.items())
                    print(f"{agent_name}: {handler_name}({parms})")
                    handler = TOOL_HANDLERS.get(handler_name)
                    output = handler(**block.input) if handler else f"Error: Unknown tool {handler_name}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        
        rounds_since_todo = 0 if used_todo else rounds_since_todo+1
        if rounds_since_todo > 3:
            results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})   
        
        messages.append({"role": "user", "content": results})

        if manual_compact:
            print("[manual compact]")
            messages[:] = auto_compact(messages)
        
    

CHILD_TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),
    "compact":    lambda **kw: "Manual compression requested.",
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
    {"name": "compact", "description": "Trigger manual conversation compression.",
     "input_schema": {"type": "object", "properties": {"focus": {"type": "string", "description": "What to preserve in the summary"}}}},
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
        
        print(f"estimate_tokens: {estimate_tokens(context)},context_length: {len(context)}")
        
        print(f"agent: ")
        for block in context[-1]['content']:
            if block.type == 'text':
                print(f"{block.text}")

"""
$ python s06.context_compact.py 

 >> Read every Python file one by one
 
agent: bash(command='find /mnt/d/Projects/learn-claude-code -name "*.py...')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s00.anthropic-te...')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s00.ollama-test....')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s00.openai-test....')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s01.agent_loop.p...')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s02_tool_use.py')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s03.todo_write.p...')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s04.subagent.py')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s05.skill_loadin...')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/s06.context_comp...')
estimate_tokens: 16619,context_length: 6
agent:
Read all 9 Python files:

| File | Description |
|------|-------------|
| `s00.anthropic-test.py` | Basic agent loop with Anthropic API + thinking |
| `s00.ollama-test.py` | Basic agent loop with Ollama streaming |
| `s00.openai-test.py` | Basic agent loop with OpenAI API + streaming |
| `s01.agent_loop.py` | Agent loop with bash tool support |
| `s02_tool_use.py` | Multi-tool: bash, read_file, write_file, edit_file |
| `s03.todo_write.py` | Added todo management for task tracking |
| `s04.subagent.py` | Added subagent spawning with task delegation |
| `s05.skill_loading.py` | Added skill loading system for specialized knowledge |
| `s06.context_compact.py` | Added conversation compression (micro + auto compact) |

 >> Use the compact tool to manually compress the conversation
 
[manual compact]
[transcript saved: /mnt/d/Projects/learn-claude-code/.transcripts/transcript_1774386562.jsonl]
agent: bash(command='ls -la /mnt/d/Projects/learn-claude-code/')
agent: bash(command='ls -la /mnt/d/Projects/learn-claude-code/skills/')
agent: read_file(path='/mnt/d/Projects/learn-claude-code/README.md')
agent: todo(items="[{'id': '1', 'text': 'Read and analyze all Python ...")
estimate_tokens: 2379,context_length: 11
agent:
Ready for next task. Project context loaded:
- 8 Python files (s00-s06) implementing progressive agent capabilities
- 3 skill modules (code-review, mcp-builder, pdf)
- Conversation compressed with project structure preserved

 >>
"""