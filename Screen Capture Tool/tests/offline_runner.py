import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
os.chdir(ROOT)
for key in list(os.environ):
    if key.endswith('API_KEY'):
        os.environ.pop(key, None)
os.environ['CODESNAP_DEEP'] = '0'
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False

blocked = []
def deny(*args, **kwargs):
    blocked.append('network/provider request blocked')
    raise RuntimeError('Offline audit: network and provider requests are disabled')
original_connect = socket.socket.connect
def connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        return deny()
    return original_connect(self, address)
socket.socket.connect = connect
socket.create_connection = deny
import anthropic
anthropic.resources.messages.Messages.create = deny
anthropic.resources.messages.AsyncMessages.create = deny
import pytest
result = pytest.main(sys.argv[1:])
print(f'Offline audit guard: {len(blocked)} network/provider attempts blocked; zero allowed.')
raise SystemExit(result)
