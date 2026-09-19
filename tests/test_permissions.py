"""三角色权限矩阵：运营只读、工程师可写数据与训练、管理员全量。

单 TestClient 内切换登录（同一 worker，避免多进程）；工程师的训练任务
真实执行完成后，管理员再发布，保证断言确定性。
"""

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import store
from backend.main import app

ACCOUNTS = {'test_engineer': ('engineer', 'Engineer12345'),
            'test_operator': ('operator', 'Operator12345')}

STAMPS = pd.date_range('2026-03-01', periods=420, freq='h').strftime('%Y-%m-%d %H:%M:%S')
CSV = 'timestamp,load\n' + '\n'.join(f'{stamp},{800 + index * 3}' for index, stamp in enumerate(STAMPS)) + '\n'


def login(client, username, password):
    logged = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert logged.status_code == 200, logged.text


def wait_ready(model_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if store.one("SELECT status FROM models WHERE id=?", (model_id,))['status'] in ('ready', 'failed'):
            return store.one("SELECT status FROM models WHERE id=?", (model_id,))['status']
        time.sleep(1)
    raise TimeoutError(f'模型 {model_id} 训练超时')


@pytest.fixture(scope='module')
def client(admin_client):
    store.execute("DELETE FROM users WHERE username LIKE 'test_%'")
    for username, (role, password) in ACCOUNTS.items():
        created = admin_client.post('/api/users', json={'username': username, 'password': password, 'role': role})
        assert created.status_code == 201, created.text
    with TestClient(app) as session:
        yield session


def test_operator_is_read_only(client):
    login(client, 'test_operator', 'Operator12345')
    assert client.get('/api/datasets').status_code == 200
    assert client.get('/api/dashboard').status_code == 200
    upload = client.post('/api/datasets/upload', files={'file': ('a.csv', CSV, 'text/csv')},
                         data={'name': '越权上传', 'scene': '园区'})
    assert upload.status_code == 403
    assert client.post('/api/models/train', json={'dataset_id': 'x', 'name': '越权训练',
                                                  'kind': 'seasonal'}).status_code == 403
    assert client.post('/api/models/x/publish').status_code == 403
    assert client.get('/api/users').status_code == 403
    assert client.post('/api/users', json={'username': 'hacker', 'password': 'Hack12345',
                                           'role': 'admin'}).status_code == 403


def test_engineer_writes_data_and_trains_but_not_administration(client):
    login(client, 'test_engineer', 'Engineer12345')
    upload = client.post('/api/datasets/upload', files={'file': ('b.csv', CSV, 'text/csv')},
                         data={'name': '工程师上传', 'scene': '园区'})
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()['id']
    assert client.get(f'/api/datasets/{dataset_id}').status_code == 200
    train = client.post('/api/models/train', json={'dataset_id': dataset_id, 'name': '工程师基线',
                                                   'kind': 'seasonal', 'horizon': 24})
    assert train.status_code == 202, train.text
    assert wait_ready(train.json()['model_id']) == 'ready'
    assert client.get('/api/users').status_code == 403
    assert client.put('/api/settings/learning', json={'enabled': True, 'auto_forecast': False,
                                                      'minimum_points': 48, 'cooldown_hours': 24,
                                                      'error_threshold': 15.0}).status_code == 403


def test_admin_administrates_and_publishes(client):
    login(client, 'admin', 'Admin12345')
    names = {row['username'] for row in client.get('/api/users').json()}
    assert {'test_engineer', 'test_operator'} <= names
    assert client.put('/api/settings/learning', json={'enabled': False, 'auto_forecast': False,
                                                      'minimum_points': 48, 'cooldown_hours': 24,
                                                      'error_threshold': 15.0}).status_code == 200
    model = store.one("SELECT * FROM models WHERE name='工程师基线'")
    assert model is not None and model['status'] == 'ready'
    assert client.post(f"/api/models/{model['id']}/publish").status_code == 200
    assert store.one('SELECT status FROM models WHERE id=?', (model['id'],))['status'] == 'active'
