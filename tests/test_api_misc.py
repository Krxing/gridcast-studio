"""杂项接口：模型对比、任务取消守卫、修改自己密码、登录限速。"""

import time

import pandas as pd
import pytest

from backend import security, store

STAMPS = pd.date_range('2026-04-01', periods=420, freq='h').strftime('%Y-%m-%d %H:%M:%S')
CSV = 'timestamp,load\n' + '\n'.join(f'{stamp},{600 + index * 3}' for index, stamp in enumerate(STAMPS)) + '\n'


def wait_ready(model_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = store.one("SELECT status FROM models WHERE id=?", (model_id,))['status']
        if status in ('ready', 'failed'):
            return status
        time.sleep(1)
    raise TimeoutError(f'模型 {model_id} 训练超时')


@pytest.fixture(scope='module')
def models(admin_client):
    upload = admin_client.post('/api/datasets/upload', files={'file': ('misc.csv', CSV, 'text/csv')},
                               data={'name': '对比验证数据', 'scene': '园区'})
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()['id']
    ids = []
    for index in range(2):
        train = admin_client.post('/api/models/train', json={'dataset_id': dataset_id,
                                                             'name': f'对比模型 {index}', 'kind': 'seasonal'})
        assert train.status_code == 202, train.text
        assert wait_ready(train.json()['model_id']) == 'ready'
        ids.append(train.json()['model_id'])
    return ids


def test_compare_requires_two_models(admin_client):
    assert admin_client.get('/api/models/compare', params={'ids': 'single-id'}).status_code == 422


def test_compare_rejects_missing_models(admin_client, models):
    response = admin_client.get('/api/models/compare', params={'ids': f'{models[0]},does-not-exist'})
    assert response.status_code == 404


def test_compare_returns_metrics(admin_client, models):
    response = admin_client.get('/api/models/compare', params={'ids': ','.join(models)})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2 and all('metrics' in row for row in rows)
    assert rows[0]['metrics']['mae'] >= 0


def test_cancel_guard_for_unknown_jobs(admin_client):
    assert admin_client.post('/api/jobs/does-not-exist/cancel').status_code == 409


def test_password_change_only_for_self(admin_client):
    created = admin_client.post('/api/users', json={'username': 'test_pw', 'password': 'OldPass123', 'role': 'operator'})
    assert created.status_code == 201
    # 管理员不能替别人改密
    assert admin_client.post('/api/auth/password',
                            json={'username': 'test_pw', 'password': 'NewPass123'}).status_code == 403
    # 本人改密后能用新密码登录
    assert admin_client.post('/api/auth/login', json={'username': 'test_pw', 'password': 'OldPass123'}).status_code == 200
    assert admin_client.post('/api/auth/password',
                            json={'username': 'test_pw', 'password': 'NewPass12345'}).status_code == 200
    assert admin_client.post('/api/auth/login', json={'username': 'test_pw', 'password': 'NewPass12345'}).status_code == 200
    assert admin_client.post('/api/auth/login', json={'username': 'test_pw', 'password': 'OldPass123'}).status_code == 401
    # 还原管理员会话，避免影响后续测试
    assert admin_client.post('/api/auth/login', json={'username': 'admin', 'password': 'Admin12345'}).status_code == 200


def test_login_rate_limit(admin_client):
    try:
        for _ in range(8):
            assert admin_client.post('/api/auth/login',
                                     json={'username': 'admin', 'password': 'wrong-password'}).status_code == 401
        assert admin_client.post('/api/auth/login', json={'username': 'admin', 'password': 'Admin12345'}).status_code == 429
    finally:
        security.ATTEMPTS.clear()
