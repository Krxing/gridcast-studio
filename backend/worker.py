import time
import traceback

from backend import engine, service, store


def run():
    store.initialize()
    while True:
        store.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('worker_heartbeat', store.encode(store.now())))
        with store.connection() as database:
            database.execute('BEGIN IMMEDIATE')
            job = store.row_dict(database.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone())
            if job:
                database.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (store.now(), job['id']))
        if job is None:
            time.sleep(1)
            continue
        try:
            payload = job['payload']
            if job['kind'] == 'train':
                model = store.one('SELECT * FROM models WHERE id=?', (payload['model_id'],))
                result = engine.train(model, payload['snapshot'], job['id'])
                if payload.get('bootstrap'):
                    service.publish(model['id'])
                    model = store.one('SELECT * FROM models WHERE id=?', (model['id'],))
                    engine.forecast(model, payload['snapshot'], 'backtest', .95)
                    result.update(engine.forecast(model, payload['snapshot'], 'future', .95))
            elif job['kind'] == 'predict':
                model = store.one('SELECT * FROM models WHERE id=?', (payload['model_id'],))
                result = engine.forecast(model, payload['snapshot'], payload['mode'], payload['confidence'])
            elif job['kind'] == 'refresh':
                result = service.refresh(payload['snapshot'])
            else:
                raise ValueError('未知任务类型')
            store.progress(job['id'], 100, '任务已完成')
            store.execute("UPDATE jobs SET status='success', result=?, updated_at=? WHERE id=?", (store.encode(result), store.now(), job['id']))
        except Exception as error:
            traceback.print_exc()
            message = str(error)[:500]
            store.progress(job['id'], 100, '任务失败：' + message)
            store.execute("UPDATE jobs SET status='failed', result=?, updated_at=? WHERE id=?", (store.encode({'error': message}), store.now(), job['id']))
            if job['kind'] == 'train':
                store.execute("UPDATE models SET status='failed' WHERE id=? AND status='training'", (job['payload']['model_id'],))
            store.event('计算任务失败', message, 'error')


if __name__ == '__main__':
    run()
