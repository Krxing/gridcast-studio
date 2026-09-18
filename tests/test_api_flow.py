"""业务闭环集成测试：云端初始化 → 演示训练 → 发布预测导出 → 重启恢复。

含真实模型训练，耗时约 1-2 分钟；快速跳过可用 pytest -m "not integration"。
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend import store
from backend.main import app

pytestmark = pytest.mark.integration

STATE = {}
TOKEN = 'pytest-token-0123456789abcdef'


def wait_job(client, job_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('success', 'failed'):
            assert job['status'] == 'success', job['result']
            return job
        time.sleep(2)
    raise TimeoutError(f'任务 {job_id} 超时')


def test_full_business_flow():
    with TestClient(app) as client:
        # 云端初始化：错误令牌 403，正确令牌建管理员
        assert client.get('/api/status').json()['setup_required']
        wrong = client.post('/api/auth/setup', json={'username': 'admin', 'password': 'Admin12345',
                                                     'setup_token': 'wrong-token'})
        assert wrong.status_code == 403
        ok = client.post('/api/auth/setup', json={'username': 'admin', 'password': 'Admin12345',
                                                  'setup_token': TOKEN})
        assert ok.status_code == 200, ok.text

        # 演示数据 + 真实训练，产物为相对路径
        seed = client.post('/api/demo/seed').json()
        wait_job(client, seed['job_id'])
        STATE['dataset_id'] = seed['dataset_id']
        dataset = store.one('SELECT * FROM datasets WHERE id=?', (seed['dataset_id'],))
        model = store.one('SELECT * FROM models WHERE dataset_id=? ORDER BY created_at DESC', (seed['dataset_id'],))
        assert dataset['path'] == f"datasets/{seed['dataset_id']}_v1.csv"
        assert model['artifact'] == f"models/{model['id']}.joblib"
        STATE['model_id'] = model['id']

        # 发布 + 未来预测 + CSV 导出
        assert client.post(f"/api/models/{model['id']}/publish").status_code == 200
        run = client.post('/api/predictions/run', json={'model_id': model['id'], 'dataset_id': seed['dataset_id'],
                                                        'mode': 'future', 'confidence': 0.95}).json()
        wait_job(client, run['job_id'])
        forecast = client.get('/api/predictions').json()[0]
        export = client.get(f"/api/predictions/{forecast['id']}/export")
        assert export.status_code == 200 and b'timestamp' in export.content


def test_state_survives_restart():
    with TestClient(app) as restarted:
        assert restarted.post('/api/auth/login', json={'username': 'admin', 'password': 'Admin12345'}).status_code == 200
        detail = restarted.get(f"/api/datasets/{STATE['dataset_id']}")
        assert detail.status_code == 200 and len(detail.json()['series']) > 100
        run = restarted.post('/api/predictions/run', json={'model_id': STATE['model_id'],
                                                            'dataset_id': STATE['dataset_id'],
                                                            'mode': 'backtest', 'confidence': 0.9}).json()
        wait_job(restarted, run['job_id'])
