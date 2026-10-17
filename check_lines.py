with open(r'app\chat\services\chat_service.py', 'r') as f:
    lines = f.readlines()
for i in range(703, 710):
    print(f'{i+1}: {repr(lines[i])}')