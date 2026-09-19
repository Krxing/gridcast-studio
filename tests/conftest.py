"""测试环境：在导入 backend 前固定环境变量，使用独立数据目录，避免污染 .data。

注意：不得在本文件模块级导入 backend——pytest_sessionstart 会清空数据目录，
必须让 backend.store 的建目录逻辑发生在清空之后的首次真正使用时。
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / '.qa' / 'pytest-data'
os.environ['APP_MODE'] = 'cloud'
os.environ['APP_DATA_DIR'] = str(DATA_DIR)
os.environ['APP_SETUP_TOKEN'] = 'pytest-token-0123456789abcdef'


def pytest_sessionstart(session):
    shutil.rmtree(DATA_DIR, ignore_errors=True)


def _ensure_admin(client):
    """单文件运行也能自举管理员；整仓运行时直接登录已存在的账号。"""
    if client.get('/api/status').json()['setup_required']:
        created = client.post('/api/auth/setup', json={'username': 'admin', 'password': 'Admin12345',
                                                       'setup_token': os.environ['APP_SETUP_TOKEN']})
        assert created.status_code == 200, created.text
    else:
        logged = client.post('/api/auth/login', json={'username': 'admin', 'password': 'Admin12345'})
        assert logged.status_code == 200, logged.text


import pytest  # noqa: E402


@pytest.fixture(scope='module')
def admin_client():
    """已登录管理员的独立会话；每个测试文件一个，worker 随 lifespan 串行启停。"""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        _ensure_admin(client)
        yield client
