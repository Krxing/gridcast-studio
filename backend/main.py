import importlib.util
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from typing import Literal

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from statsmodels.tsa.seasonal import STL

from backend import datasets, engine, security, service, store


def _start_worker(root, data):
    output = (data / 'worker.log').open('a', encoding='utf-8')
    process = subprocess.Popen(
        [sys.executable, '-u', '-m', 'backend.worker'], cwd=root,
        stdout=output, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    return process, output


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    with store.connection() as database:
        interrupted = database.execute("SELECT id, payload, kind FROM jobs WHERE status='running'").fetchall()
        for record in interrupted:
            job = store.row_dict(record)
            database.execute("UPDATE jobs SET status='failed', result=?, updated_at=? WHERE id=?",
                             (store.encode({'error': '服务重启中断了计算，请重新提交任务'}), store.now(), job['id']))
            if job['kind'] == 'train':
                database.execute("UPDATE models SET status='failed' WHERE id=? AND status='training'", (job['payload']['model_id'],))

    worker, output = _start_worker(store.ROOT, store.DATA)
    app.state.worker = worker
    stop_event = threading.Event()

    def _watchdog():
        while not stop_event.wait(timeout=10):
            if app.state.worker.poll() is not None:
                store.event('计算进程已退出，正在重启', level='warning')
                new_worker, _ = _start_worker(store.ROOT, store.DATA)
                app.state.worker = new_worker

    watchdog = threading.Thread(target=_watchdog, daemon=True, name='worker-watchdog')
    watchdog.start()

    yield

    stop_event.set()
    app.state.worker.terminate()
    try:
        app.state.worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        app.state.worker.kill()
        app.state.worker.wait()
    output.close()


app = FastAPI(title='GridCast 用电负荷预测系统', version='1.0.0', lifespan=lifespan)


@app.middleware('http')
async def protect_origin(request: Request, call_next):
    if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        origin = request.headers.get('origin')
        host = request.headers.get('host', '')
        allowed = {f'http://{host}', f'https://{host}', os.environ.get('APP_PUBLIC_ORIGIN', '')}
        if origin and origin not in allowed:
            return JSONResponse({'detail': '不允许跨站写入请求'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def value_error(request, error):
    return JSONResponse({'detail': str(error)}, status_code=422)


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request, error):
    return JSONResponse({'detail': '记录已存在或仍被其他记录引用，操作未执行'}, status_code=409)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_\-]+$')
    password: str = Field(min_length=1, max_length=72)
    setup_token: str = ''


class NewUser(Credentials):
    role: Literal['admin', 'engineer', 'operator'] = 'operator'


class TrainRequest(BaseModel):
    dataset_id: str
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['ensemble', 'hybrid', 'seasonal'] = 'ensemble'
    horizon: int = Field(default=24, ge=2, le=168)
    epochs: int = Field(default=12, ge=2, le=100)


class PredictRequest(BaseModel):
    model_id: str
    dataset_id: str
    mode: Literal['future', 'backtest'] = 'future'
    confidence: Literal[0.8, 0.9, 0.95] = .95


class LearningRequest(BaseModel):
    enabled: bool = False
    auto_forecast: bool = False
    minimum_points: int = Field(default=48, ge=2, le=10000)
    cooldown_hours: float = Field(default=24, ge=0, le=720)
    error_threshold: float = Field(default=15, ge=.1, le=500)


class AppendRequest(BaseModel):
    rows: list[dict] = Field(min_length=2, max_length=10000)


def public_dataset(row):
    return {key: value for key, value in row.items() if key != 'path'}


def public_model(row):
    return {key: value for key, value in row.items() if key != 'artifact'}


def public_job(row):
    result = {key: value for key, value in row.items() if key != 'payload'}
    result['model_id'] = row['payload'].get('model_id')
    result['dataset_id'] = row['payload'].get('snapshot', {}).get('id')
    return result


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '1.0.0'}


@app.get('/api/status')
def status():
    return {'setup_required': store.one('SELECT COUNT(*) AS count FROM users')['count'] == 0,
            'mode': os.environ.get('APP_MODE', 'local'),
            'hybrid_available': importlib.util.find_spec('torch') is not None}


@app.post('/api/auth/setup')
def setup(body: Credentials, request: Request, response: Response):
    cloud = os.environ.get('APP_MODE', 'local') == 'cloud'
    remote = request.client and request.client.host not in ['127.0.0.1', '::1', 'testclient']
    if cloud or remote:
        expected = os.environ.get('APP_SETUP_TOKEN', '')
        if len(expected) < 16 or not secrets.compare_digest(body.setup_token, expected):
            raise HTTPException(403, '云端初始化需要管理员配置至少 16 位 APP_SETUP_TOKEN，并填入正确令牌')
    hashed = security.password_hash(body.password)
    with store.connection() as database:
        database.execute('BEGIN IMMEDIATE')
        if database.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0:
            raise HTTPException(409, '管理员已创建，请直接登录')
        user = {'id': store.uid(), 'username': body.username, 'role': 'admin', 'created_at': store.now()}
        database.execute('INSERT INTO users VALUES (?,?,?,?,?)', (user['id'], user['username'], hashed, 'admin', user['created_at']))
    security.session(response, user)
    store.event('管理员初始化完成', body.username)
    return user


@app.post('/api/auth/login')
def login(body: Credentials, request: Request, response: Response):
    return security.login(request, response, body.username, body.password)


@app.post('/api/auth/logout')
def logout(response: Response):
    response.delete_cookie('gridcast_session')
    return {'ok': True}


@app.get('/api/me')
def me(user=Depends(security.current_user)):
    return user


@app.get('/api/datasets')
def list_datasets(user=Depends(security.current_user)):
    return [public_dataset(row) for row in store.many('SELECT * FROM datasets ORDER BY created_at DESC')]


@app.post('/api/datasets/upload', status_code=201)
async def upload(file: UploadFile = File(...), name: str = Form(...), scene: str = Form('园区'), user=Depends(security.engineer)):
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(422, '仅支持 CSV 文件')
    if not name.strip():
        raise HTTPException(422, '请填写数据集名称')
    content = await file.read(20 * 1024 * 1024 + 1)
    return public_dataset(datasets.save_new(datasets.read_csv(content), name, scene))


@app.get('/api/datasets/template')
def template(user=Depends(security.current_user)):
    content = 'timestamp,load,temperature,humidity,price,is_holiday\n2026-01-01 00:00:00,550,22,60,0.38,1\n2026-01-01 01:00:00,530,21,62,0.38,1\n'
    return Response('\ufeff' + content, media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="dataset-template.csv"'})


@app.get('/api/datasets/{dataset_id}')
def dataset_detail(dataset_id: str, user=Depends(security.current_user)):
    snapshot = datasets.get_dataset(dataset_id)
    frame = datasets.load_frame(snapshot)
    return {'dataset': public_dataset(snapshot), 'series': datasets.series(frame),
            'preview': datasets.series(frame.head(12)), 'columns': list(frame.columns)}


@app.get('/api/datasets/{dataset_id}/decomposition')
def decomposition(dataset_id: str, user=Depends(security.current_user)):
    snapshot = datasets.get_dataset(dataset_id)
    frame = datasets.load_frame(snapshot).tail(6000).reset_index(drop=True)
    period = max(2, 1440 // snapshot['interval_minutes'])
    if len(frame) < period * 3:
        raise ValueError('至少需要三个完整周期进行 STL 分解')
    decomposed = STL(frame['load'].to_numpy(), period=period, robust=True).fit()
    frame = frame.assign(trend=decomposed.trend, seasonal=decomposed.seasonal, residual=decomposed.resid)
    return {'series': datasets.series(frame, 1200), 'method': 'STL 鲁棒分解，仅用于事后探索，不作为已知未来输入', 'period': period}


@app.post('/api/datasets/{dataset_id}/append', status_code=202)
def append_data(dataset_id: str, body: AppendRequest, user=Depends(security.engineer)):
    snapshot = datasets.append(dataset_id, pd.DataFrame(body.rows))
    job_id = store.create_job('refresh', {'snapshot': snapshot})
    return {'dataset': public_dataset(snapshot), 'job_id': job_id}


@app.post('/api/datasets/{dataset_id}/append-file', status_code=202)
async def append_file(dataset_id: str, file: UploadFile = File(...), user=Depends(security.engineer)):
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise ValueError('仅支持 CSV 文件')
    snapshot = datasets.append(dataset_id, datasets.read_csv(await file.read(20 * 1024 * 1024 + 1)))
    return {'dataset': public_dataset(snapshot), 'job_id': store.create_job('refresh', {'snapshot': snapshot})}


@app.delete('/api/datasets/{dataset_id}')
def delete_dataset(dataset_id: str, user=Depends(security.administrator)):
    snapshot = datasets.get_dataset(dataset_id)
    if store.one('SELECT id FROM models WHERE dataset_id=?', (dataset_id,)):
        raise HTTPException(409, '该数据集已有模型引用，为保留可复现性不能删除')
    if any(row['payload'].get('snapshot', {}).get('id') == dataset_id for row in store.many("SELECT * FROM jobs WHERE status IN ('pending','running')")):
        raise HTTPException(409, '该数据集正在被计算任务使用')
    store.execute('DELETE FROM datasets WHERE id=?', (dataset_id,))
    for path in (store.DATA / 'datasets').glob(f'{snapshot["id"]}_v*.csv'):
        path.unlink()
    store.event('未引用的数据集已删除', snapshot['name'], 'warning')
    return {'ok': True}


@app.post('/api/demo/seed', status_code=202)
def seed(user=Depends(security.engineer)):
    existing = store.one('SELECT * FROM datasets WHERE is_demo=1 ORDER BY created_at LIMIT 1')
    if existing:
        return {'dataset_id': existing['id'], 'existing': True}
    start = pd.Timestamp.now(tz='Asia/Shanghai').normalize().tz_localize(None) - pd.Timedelta(days=90)
    snapshot = datasets.save_new(datasets.synthetic(start, 90 * 24), '青禾产业园 · 合成演示数据', '产业园区', True)
    result = service.queue_training(snapshot, '集成负荷模型 v1', 'ensemble', 24, bootstrap=True)
    result['dataset_id'] = snapshot['id']
    return result


@app.post('/api/demo/{dataset_id}/advance', status_code=202)
def advance(dataset_id: str, user=Depends(security.engineer)):
    snapshot = datasets.get_dataset(dataset_id)
    if not snapshot['is_demo']:
        raise HTTPException(422, '只能推进合成演示数据，不能给真实数据生成伪造观测值')
    new_count = snapshot['rows'] + 24
    if new_count > datasets.MAX_ROWS:
        raise ValueError('已达到演示数据上限')
    full = datasets.synthetic(snapshot['start'], new_count, interval=snapshot['interval_minutes'])
    updated = datasets.append(dataset_id, full.tail(24))
    return {'dataset': public_dataset(updated), 'job_id': store.create_job('refresh', {'snapshot': updated})}


@app.get('/api/models')
def list_models(user=Depends(security.current_user)):
    return [public_model(row) for row in store.many('SELECT * FROM models ORDER BY created_at DESC')]


@app.get('/api/models/compare')
def compare_models(ids: str = Query(..., description='逗号分隔的模型 ID 列表，最多 8 个'),
                   user=Depends(security.current_user)):
    id_list = [item.strip() for item in ids.split(',') if item.strip()][:8]
    if len(id_list) < 2:
        raise HTTPException(422, '至少提供 2 个模型 ID')
    rows = [store.one('SELECT * FROM models WHERE id=?', (model_id,)) for model_id in id_list]
    missing = [model_id for model_id, row in zip(id_list, rows, strict=True) if row is None]
    if missing:
        raise HTTPException(404, f'找不到以下模型：{", ".join(missing)}')
    return [public_model(row) for row in rows]


@app.post('/api/models/train', status_code=202)
def train_model(body: TrainRequest, user=Depends(security.engineer)):
    if body.kind == 'hybrid' and importlib.util.find_spec('torch') is None:
        raise HTTPException(422, '未安装 PyTorch，请先安装 requirements-hybrid.txt')
    snapshot = datasets.get_dataset(body.dataset_id)
    return service.queue_training(snapshot, body.name, body.kind, body.horizon, body.epochs)


@app.get('/api/models/{model_id}')
def model_detail(model_id: str, user=Depends(security.current_user)):
    row = store.one('SELECT * FROM models WHERE id=?', (model_id,))
    if row is None:
        raise HTTPException(404, '模型不存在')
    return public_model(row)


@app.post('/api/models/{model_id}/publish')
def publish_model(model_id: str, user=Depends(security.administrator)):
    service.publish(model_id)
    return {'ok': True}


@app.post('/api/predictions/run', status_code=202)
def predict(body: PredictRequest, user=Depends(security.current_user)):
    model = store.one('SELECT * FROM models WHERE id=?', (body.model_id,))
    if model is None or model['status'] not in ['ready', 'active', 'archived']:
        raise HTTPException(422, '请选择训练成功的模型')
    if model['dataset_id'] != body.dataset_id:
        raise HTTPException(422, '请使用该模型对应的数据集，原型不支持未验证的跨场景迁移')
    if store.one("SELECT COUNT(*) AS count FROM jobs WHERE status IN ('pending','running')")['count'] >= 12:
        raise HTTPException(429, '任务队列已满')
    snapshot = datasets.get_dataset(body.dataset_id)
    return {'job_id': store.create_job('predict', {'model_id': model['id'], 'snapshot': snapshot, 'mode': body.mode, 'confidence': body.confidence})}


@app.get('/api/predictions')
def list_predictions(user=Depends(security.current_user)):
    records = store.many('SELECT * FROM forecasts ORDER BY created_at DESC LIMIT 100')
    return [{**{key: value for key, value in row.items() if key != 'result'},
             'model_name': row['result']['model_name'], 'dataset_name': row['result']['dataset_name'],
             'peak': row['result']['peak'], 'is_demo': row['result']['is_demo']} for row in records]


def get_forecast(forecast_id):
    record = store.one('SELECT * FROM forecasts WHERE id=?', (forecast_id,))
    if record is None:
        raise HTTPException(404, '预测记录不存在')
    return engine.enrich_forecast(record)


@app.get('/api/predictions/{forecast_id}')
def prediction_detail(forecast_id: str, user=Depends(security.current_user)):
    return get_forecast(forecast_id)


@app.get('/api/predictions/{forecast_id}/export')
def export(forecast_id: str, user=Depends(security.current_user)):
    record = get_forecast(forecast_id)
    frame = pd.DataFrame(record['result']['series'])
    frame['confidence'] = record['confidence']
    frame['model_id'] = record['model_id']
    frame['dataset_version'] = record['dataset_version']
    frame['is_demo'] = record['result']['is_demo']
    frame['origin'] = record['origin']
    frame['mode'] = record['mode']
    return Response('\ufeff' + frame.to_csv(index=False), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="forecast-{forecast_id}.csv"'})


@app.get('/api/jobs')
def list_jobs(user=Depends(security.current_user)):
    return [public_job(row) for row in store.many('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50')]


@app.get('/api/jobs/{job_id}')
def job_detail(job_id: str, user=Depends(security.current_user)):
    row = store.one('SELECT * FROM jobs WHERE id=?', (job_id,))
    if row is None:
        raise HTTPException(404, '任务不存在')
    return public_job(row)


@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id: str, user=Depends(security.engineer)):
    with store.connection() as database:
        database.execute('BEGIN IMMEDIATE')
        row = store.row_dict(database.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
        if not row or row['status'] != 'pending':
            raise HTTPException(409, '只可取消尚未开始的任务')
        database.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE id=?", (store.now(), job_id))
        if row['kind'] == 'train':
            database.execute("UPDATE models SET status='failed' WHERE id=?", (row['payload']['model_id'],))
    return {'ok': True}


@app.get('/api/dashboard')
def dashboard(user=Depends(security.current_user)):
    latest = store.one('SELECT * FROM forecasts ORDER BY created_at DESC LIMIT 1')
    active = store.many("SELECT * FROM models WHERE status='active' ORDER BY created_at DESC")
    return {'dataset_count': store.one('SELECT COUNT(*) AS count FROM datasets')['count'],
            'model_count': store.one("SELECT COUNT(*) AS count FROM models WHERE status IN ('ready','active','archived')")['count'],
            'forecast_count': store.one('SELECT COUNT(*) AS count FROM forecasts')['count'],
            'running_jobs': store.one("SELECT COUNT(*) AS count FROM jobs WHERE status IN ('pending','running')")['count'],
            'latest_forecast': engine.enrich_forecast(latest) if latest else None,
            'active_models': [public_model(row) for row in active],
            'events': store.many('SELECT * FROM events ORDER BY created_at DESC LIMIT 12'),
            'worker_alive': app.state.worker.poll() is None,
            'mode': os.environ.get('APP_MODE', 'local')}


@app.get('/api/settings')
def get_settings(user=Depends(security.current_user)):
    return {'learning': store.setting('learning'),
            'monitors': [row['value'] for row in store.many("SELECT value FROM settings WHERE key LIKE 'monitor:%'")],
            'worker_alive': app.state.worker.poll() is None,
            'mode': os.environ.get('APP_MODE', 'local'), 'timezone': 'Asia/Shanghai',
            'hybrid_available': importlib.util.find_spec('torch') is not None}


@app.put('/api/settings/learning')
def update_learning(body: LearningRequest, user=Depends(security.administrator)):
    store.execute('UPDATE settings SET value=? WHERE key=?', (store.encode(body.model_dump()), 'learning'))
    store.event('自适应策略已更新', f'自动预测 {body.auto_forecast} · 受控重训 {body.enabled} · 仍需人工上线')
    return body.model_dump()


@app.get('/api/events')
def events(user=Depends(security.current_user)):
    return store.many('SELECT * FROM events ORDER BY created_at DESC LIMIT 100')


@app.get('/api/users')
def users(user=Depends(security.administrator)):
    return [security.public_user(row) for row in store.many('SELECT * FROM users ORDER BY created_at')]


@app.post('/api/users', status_code=201)
def create_user(body: NewUser, user=Depends(security.administrator)):
    user_id = store.uid()
    store.execute('INSERT INTO users VALUES (?,?,?,?,?)', (user_id, body.username, security.password_hash(body.password), body.role, store.now()))
    store.event('用户已创建', f'{body.username} · {body.role}')
    return {'id': user_id}


@app.post('/api/auth/password')
def change_password(body: Credentials, user=Depends(security.current_user)):
    if body.username != user['username']:
        raise HTTPException(403, '只能修改自己的密码')
    store.execute('UPDATE users SET password=? WHERE id=?', (security.password_hash(body.password), user['id']))
    store.event('用户密码已更新', user['username'])
    return {'ok': True}


frontend = store.ROOT / 'frontend' / 'dist'
if frontend.exists():
    app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
else:
    @app.get('/')
    def no_frontend():
        return {'message': '请先在 frontend 执行 npm install 和 npm run build，或运行前端开发服务器'}
