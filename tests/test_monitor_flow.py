"""自适应学习闭环：低门槛策略下追加数据 → 监控更新 + 自动预测 + 候选重训排队；
候选完成训练但线上模型不被自动替换。含真实训练，标记 integration。"""

import time

import pytest

from backend import store

pytestmark = pytest.mark.integration

DEFAULT_POLICY = {'enabled': False, 'auto_forecast': False, 'minimum_points': 48,
                  'cooldown_hours': 24, 'error_threshold': 15.0}
AGGRESSIVE = {'enabled': True, 'auto_forecast': True, 'minimum_points': 24,
              'cooldown_hours': 0, 'error_threshold': 0.1}


def wait_job(client, job_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('success', 'failed'):
            assert job['status'] == 'success', job['result']
            return job
        time.sleep(2)
    raise TimeoutError(f'任务 {job_id} 超时')


def ensure_demo(admin_client):
    dataset = store.one('SELECT * FROM datasets WHERE is_demo=1 ORDER BY created_at LIMIT 1')
    if dataset:
        return dataset
    seed = admin_client.post('/api/demo/seed').json()
    wait_job(admin_client, seed['job_id'])
    return store.one('SELECT * FROM datasets WHERE id=?', (seed['dataset_id'],))


def test_adaptive_retrain_flow(admin_client):
    dataset = ensure_demo(admin_client)
    active_before = store.one("SELECT * FROM models WHERE dataset_id=? AND status='active'", (dataset['id'],))
    assert active_before is not None, '演示初始化应已发布上线模型'
    model_count_before = store.one('SELECT COUNT(*) AS count FROM models')['count']

    try:
        assert admin_client.put('/api/settings/learning', json=AGGRESSIVE).status_code == 200
        advance = admin_client.post(f"/api/demo/{dataset['id']}/advance").json()
        job = wait_job(admin_client, advance['job_id'])
        result = job['result']

        monitor = store.setting(f"monitor:{dataset['id']}")
        assert monitor['dataset_version'] == dataset['version'] + 1
        assert monitor['observed_points'] >= 1
        assert result['retraining'] is True

        # 自动预测已为新增数据版本生成未来预测
        assert store.one("SELECT id FROM forecasts WHERE dataset_id=? AND dataset_version=? AND mode='future'",
                         (dataset['id'], dataset['version'] + 1)) is not None

        # 候选模型完成训练，且线上模型未被自动替换
        wait_job(admin_client, result['training']['job_id'])
        candidate = store.one('SELECT * FROM models WHERE id=?', (result['training']['model_id'],))
        assert candidate['status'] == 'ready'
        assert candidate['params']['previous_model_id'] == active_before['id']
        assert store.one("SELECT status FROM models WHERE id=?", (active_before['id'],))['status'] == 'active'
        assert store.one('SELECT COUNT(*) AS count FROM models')['count'] == model_count_before + 1
    finally:
        assert admin_client.put('/api/settings/learning', json=DEFAULT_POLICY).status_code == 200
