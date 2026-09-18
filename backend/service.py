from datetime import UTC, datetime

from backend import datasets, engine, store


def queue_training(snapshot, name, kind, horizon, epochs=12, previous_model_id=None, bootstrap=False):
    if store.one("SELECT COUNT(*) AS count FROM jobs WHERE status IN ('pending','running')")['count'] >= 12:
        raise ValueError('任务队列已满，请等待已有任务完成')
    model_id = store.uid()
    params = {'epochs': epochs, 'seed': 42, 'snapshot_rows': snapshot['rows'],
              'snapshot_end': snapshot['end'], 'previous_model_id': previous_model_id,
              'architecture': 'PyTorch 选择性状态递推 + 稀疏上下文注意力；非官方 Mamba 实现' if kind == 'hybrid' else kind}
    store.execute('INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (model_id, name[:100], kind, snapshot['id'], snapshot['version'], 'training', horizon,
                   store.encode(params), store.encode({}), None, store.now()))
    job_id = store.create_job('train', {'model_id': model_id, 'snapshot': snapshot, 'bootstrap': bootstrap})
    return {'job_id': job_id, 'model_id': model_id}


def publish(model_id):
    with store.connection() as database:
        database.execute('BEGIN IMMEDIATE')
        model = store.row_dict(database.execute('SELECT * FROM models WHERE id=?', (model_id,)).fetchone())
        if model is None or model['status'] not in ['ready', 'active', 'archived'] or not model['artifact']:
            raise ValueError('只能发布训练成功的模型')
        database.execute("UPDATE models SET status='archived' WHERE dataset_id=? AND status='active'", (model['dataset_id'],))
        database.execute("UPDATE models SET status='active' WHERE id=?", (model_id,))
    store.event('模型已上线', f'{model["name"]} · 旧版本保留，可再次发布以回滚')


def refresh(snapshot):
    policy = store.setting('learning')
    active = store.one("SELECT * FROM models WHERE dataset_id=? AND status='active'", (snapshot['id'],))
    if active is None:
        return {'message': '真实值可供对照；未找到上线模型，跳过自动预测和重训'}
    recent = store.many("SELECT * FROM forecasts WHERE dataset_id=? AND model_id=? AND mode='future' ORDER BY created_at DESC LIMIT 20",
                        (snapshot['id'], active['id']))
    errors = []
    observed = set()
    for record in recent:
        enriched = engine.enrich_forecast(record)
        for row in enriched['result']['series']:
            if row['actual'] is not None and row['timestamp'] not in observed:
                observed.add(row['timestamp'])
                errors.append((abs(row['point'] - row['actual']), abs(row['actual'])))
    recent_wape = float(sum(error[0] for error in errors) / max(sum(error[1] for error in errors), 1e-6) * 100) if errors else None
    frame = datasets.load_frame(snapshot)
    period = max(2, 1440 // snapshot['interval_minutes'])
    before = frame['load'].iloc[max(0, len(frame) - period * 8):-period]
    current = frame['load'].iloc[-period:]
    drift = float(abs(current.mean() - before.mean()) / max(before.std(), 1)) if len(before) else 0.0
    monitor = {'dataset_id': snapshot['id'], 'dataset_version': snapshot['version'],
               'observed_points': len(observed), 'recent_wape': round(recent_wape, 3) if recent_wape is not None else None,
               'mean_shift_z': round(drift, 3), 'drift_warning': drift > 2.5, 'updated_at': store.now(),
               'note': '漂移为最近一周期相对前七周期的均值偏移提示，不是正式统计检验'}
    store.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (f'monitor:{snapshot["id"]}', store.encode(monitor)))
    result = {'monitor': monitor, 'retraining': False}
    if policy['auto_forecast']:
        existing = store.one("SELECT id FROM forecasts WHERE dataset_id=? AND model_id=? AND dataset_version=? AND mode='future'",
                             (snapshot['id'], active['id'], snapshot['version']))
        if not existing:
            result.update(engine.forecast(active, snapshot, 'future', .95))
    new_points = snapshot['rows'] - active['params']['snapshot_rows']
    last_model = store.one('SELECT * FROM models WHERE dataset_id=? ORDER BY created_at DESC LIMIT 1', (snapshot['id'],))
    age_hours = (datetime.now(UTC) - datetime.fromisoformat(last_model['created_at'])).total_seconds() / 3600
    has_training = store.one("SELECT id FROM models WHERE dataset_id=? AND status='training'", (snapshot['id'],))
    threshold_met = (recent_wape is not None and recent_wape >= policy['error_threshold']) or drift > 2.5
    if policy['enabled'] and new_points >= policy['minimum_points'] and age_hours >= policy['cooldown_hours'] and threshold_met and not has_training:
        result['training'] = queue_training(snapshot, active['name'].split(' · 自适应')[0] + f' · 自适应 v{snapshot["version"]}',
                                            active['kind'], active['horizon'], active['params'].get('epochs', 12), active['id'])
        result['retraining'] = True
        store.event('已触发自适应重训', '候选模型训练后需人工确认上线，当前服务模型保持不变', 'warning')
    return result
