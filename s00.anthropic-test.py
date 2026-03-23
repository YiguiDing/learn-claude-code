import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(
    base_url="https://coding.dashscope.aliyuncs.com/apps/anthropic",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
)

def agent_loop():
    messages=[]
    while True:
        question = input('\nUser: ')
        messages.append({'role': 'user', 'content': [{"type": "text", "text": question }]})
        response = client.messages.create(
            model="qwen3.5-plus", max_tokens=1024,
            system=[{"type": "text", "text": 'You are a helpful assistant.'}],
            messages=messages, thinking={ "type": "enabled","budget_tokens": 1024 },
        )
        print('thinking:')
        print(response.content[0].thinking)
        print('answer:')
        print(response.content[1].text)
        messages.append({"role": "assistant", "content": response.content })

if __name__ == "__main__":
    agent_loop()