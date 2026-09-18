"""测试环境：在导入 backend 前固定环境变量，使用独立数据目录，避免污染 .data。"""

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
