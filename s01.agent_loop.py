import os
import subprocess
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(
    base_url="https://coding.dashscope.aliyuncs.com/apps/anthropic",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
)

def run_bash(command:str):
    try:
        process = subprocess.run(command, shell=True, cwd=os.getcwd(), capture_output=True, text=True, encoding='utf-8', timeout=100)
        result = (process.stdout + process.stderr).strip()
        return result[:50000]
    except subprocess.TimeoutExpired:
        return "Timeout"


TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }
    }
]
    

MODEL = "qwen3.5-plus"
MAX_TOKENS = 8000
THINKING = { "type": "enabled", "budget_tokens": 8000 }
SYSTEM = [{"type": "text", "text": f'You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don\'t explain.'}]

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
                print(f"\033[33m$ {block.input['command']}\033[0m")
                output = run_bash(block.input["command"])
                # print(output[:1000])
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
                print(block.text)