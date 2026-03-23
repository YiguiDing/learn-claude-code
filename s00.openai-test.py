import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://coding.dashscope.aliyuncs.com/v1",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
)

def agent_loop():

  messages=[]
  messages.append({'role': 'system', 'content': 'You are a helpful assistant.'})

  while True:
    
    question = input('\nUser: ')
    messages.append({'role': 'user', 'content': question})
    
    stream = client.chat.completions.create(
      model="qwen3.5-plus",
      messages=messages,
      stream=True
    )
    
    answer = []
    thinking = []
    for chunk in stream:
        if not chunk.choices:  # 跳过空chunk
            continue
        reasoning = chunk.choices[0].delta.reasoning_content
        content = chunk.choices[0].delta.content
        if reasoning:
          print(f"{reasoning}", end="", flush=True)
          thinking.append(reasoning)
        if content:
          print(f"{content}", end="", flush=True)
          answer.append(content)
    
    messages.append({'role': 'assistant', 'content': ''.join(answer)})

if __name__ == "__main__":
    agent_loop()