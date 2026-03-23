from ollama import Client

client = Client()

messages = []

while True:
  question = input('\nUser: ')
  messages.append({'role': 'user', 'content': question })
  stream = client.chat(
    model='qwen3.5:4b',
    messages=messages,
    stream=True,
    keep_alive=-1
  )
  thinking = []
  content = []
  for chunk in stream:
    if chunk.message.thinking:
      print(chunk.message.thinking, end='', flush=True)
      thinking.append(chunk.message.thinking)
    else:
      print(chunk.message.content, end='', flush=True)
      content.append(chunk.message.content)
  messages.append({'role': 'assistant', 'content': ''.join(content)})
  