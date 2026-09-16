import io
import math

import numpy as np
import pandas as pd
from fastapi import HTTPException

from backend import store

MAX_ROWS = 100_000
OPTIONAL = ['temperature', 'humidity', 'price', 'is_holiday']


def read_csv(content):
    if len(content) > 20 * 1024 * 1024:
        raise ValueError('文件超过 20 MB，请按场景分批导入')
    for encoding in ['utf-8-sig', 'gb18030']:
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('无法识别 CSV 编码，请使用 UTF-8')


def validate(frame, expected_interval=None):
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError('存在重复列名，请确保字段名称唯一')
    if not {'timestamp', 'load'} <= set(frame.columns):
        raise ValueError('CSV 必须包含 timestamp 和 load 列，负荷单位为 kW')
    if not 2 <= len(frame) <= MAX_ROWS:
        raise ValueError('数据需包含 2 至 100000 行')
    frame = frame[['timestamp', 'load'] + [column for column in OPTIONAL if column in frame]]
    frame['timestamp'] = pd.to_datetime(frame['timestamp'], errors='coerce', format='mixed')
    if frame['timestamp'].isna().any():
        raise ValueError('存在无法解析的时间，请使用 YYYY-MM-DD HH:mm:ss')
    try:
        if frame['timestamp'].dt.tz is not None:
            frame['timestamp'] = frame['timestamp'].dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    except AttributeError as error:
        raise ValueError('时间戳时区必须一致，不能混用有时区和无时区时间') from error
    if (frame['timestamp'].dt.microsecond != 0).any() or (frame['timestamp'].dt.nanosecond != 0).any():
        raise ValueError('时间戳精度需为整秒，请移除小数秒')
    duplicate_count = int(frame.duplicated('timestamp').sum())
    frame = frame.drop_duplicates('timestamp', keep='last').sort_values('timestamp').reset_index(drop=True)
    if len(frame) < 2:
        raise ValueError('至少需要两个不同时间戳')
    for column in frame.columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors='coerce').replace([np.inf, -np.inf], np.nan)
    if frame['load'].isna().any():
        raise ValueError('load 列存在空值或非数值，请补全真实负荷；系统不会静默伪造标签')
    if (frame['load'] < 0).any():
        raise ValueError('负荷不能为负，本原型不含净上网功率')
    differences = frame['timestamp'].diff().dropna().dt.total_seconds() / 60
    interval = int(expected_interval or differences.mode().iloc[0])
    if interval < 5 or interval > 1440 or 1440 % interval:
        raise ValueError('采样间隔需为 5 分钟至 1 天且能整除 1440 分钟')
    if not np.allclose(differences.to_numpy(), interval):
        raise ValueError('时间序列不连续或间隔不一致，请补齐缺失时间点；系统不自动插值负荷')
    lower = float(frame['load'].quantile(.25))
    upper = float(frame['load'].quantile(.75))
    spread = upper - lower
    abnormal = int(((frame['load'] < lower - 3 * spread) | (frame['load'] > upper + 3 * spread)).sum())
    missing = {column: round(float(frame[column].isna().mean()) * 100, 2) for column in OPTIONAL if column in frame}
    warnings = []
    if duplicate_count:
        warnings.append(f'已去除 {duplicate_count} 个重复时间戳，保留最后一条')
    if abnormal:
        warnings.append(f'{abnormal} 个统计异常点已保留，请结合业务核查')
    if len(frame) < max(240, 1440 // interval * 20):
        warnings.append('数据较少，可能不足以进行独立的训练、校准和测试')
    quality = {'duplicates_removed': duplicate_count, 'outliers': abnormal,
               'missing_percent': missing, 'warnings': warnings,
               'min': round(float(frame['load'].min()), 2), 'max': round(float(frame['load'].max()), 2),
               'mean': round(float(frame['load'].mean()), 2), 'timezone': 'Asia/Shanghai', 'unit': 'kW'}
    return frame, interval, quality


def get_dataset(dataset_id):
    dataset = store.one('SELECT * FROM datasets WHERE id=?', (dataset_id,))
    if dataset is None:
        raise HTTPException(404, '数据集不存在')
    return dataset


def load_frame(dataset):
    frame = pd.read_csv(dataset['path'])
    frame['timestamp'] = pd.to_datetime(frame['timestamp'])
    return frame


def save_new(frame, name, scene, is_demo=False):
    frame, interval, quality = validate(frame)
    dataset_id = store.uid()
    path = store.DATA / 'datasets' / f'{dataset_id}_v1.csv'
    frame.to_csv(path, index=False)
    store.execute('INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (dataset_id, name.strip()[:100], scene[:60], int(is_demo), 1, len(frame), interval,
                   frame['timestamp'].iloc[0].isoformat(), frame['timestamp'].iloc[-1].isoformat(),
                   str(path), store.encode(quality), store.now()))
    store.event('数据集已创建', f'{name} · {len(frame)} 条 · {interval} 分钟')
    return get_dataset(dataset_id)


def append(dataset_id, new_frame):
    with store.connection() as database:
        database.execute('BEGIN IMMEDIATE')
        dataset = store.row_dict(database.execute('SELECT * FROM datasets WHERE id=?', (dataset_id,)).fetchone())
        if dataset is None:
            raise ValueError('数据集不存在')
        previous = load_frame(dataset)
        new_frame, _, _ = validate(new_frame, dataset['interval_minutes'])
        if new_frame['timestamp'].iloc[0] <= previous['timestamp'].iloc[-1]:
            raise ValueError('增量数据必须晚于现有数据，不能覆盖历史记录')
        combined, _, quality = validate(pd.concat([previous, new_frame], ignore_index=True), dataset['interval_minutes'])
        version = dataset['version'] + 1
        path = store.DATA / 'datasets' / f'{dataset_id}_v{version}.csv'
        combined.to_csv(path, index=False)
        database.execute('UPDATE datasets SET version=?, rows=?, end=?, path=?, quality=? WHERE id=?',
                         (version, len(combined), combined['timestamp'].iloc[-1].isoformat(), str(path), store.encode(quality), dataset_id))
    store.event('增量数据已接入', f'{dataset["name"]} · 新增 {len(new_frame)} 条 · v{version}')
    return get_dataset(dataset_id)


def series(frame, limit=1500):
    step = max(1, math.ceil(len(frame) / limit))
    selected = frame.iloc[::step].copy()
    if selected.index[-1] != frame.index[-1]:
        selected = pd.concat([selected, frame.iloc[[-1]]])
    selected['timestamp'] = selected['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S')
    return selected.replace({np.nan: None}).to_dict('records')


def synthetic(start, periods, seed=42, interval=60):
    timestamps = pd.date_range(start, periods=periods, freq=f'{interval}min')
    generator = np.random.default_rng(seed)
    hours = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60
    days = timestamps.dayofweek.to_numpy()
    elapsed = np.arange(periods) * interval / 60
    temperature = 24 + 6 * np.sin(2 * np.pi * (hours - 8) / 24) + 2 * np.sin(elapsed / (24 * 13))
    temperature += generator.normal(0, .8, periods)
    humidity = 66 - (temperature - 24) * 1.8 + generator.normal(0, 3, periods)
    price = np.where((hours >= 10) & (hours < 22), .92, .38)
    holiday = (days >= 5).astype(int)
    morning = 240 * np.exp(-((hours - 11) / 3.5) ** 2)
    evening = 320 * np.exp(-((hours - 18) / 3.2) ** 2)
    load = 550 + morning + evening + 15 * np.maximum(temperature - 23, 0) - 100 * holiday
    load += .014 * elapsed + generator.normal(0, 18, periods)
    return pd.DataFrame({'timestamp': timestamps, 'load': np.round(load, 2),
                         'temperature': np.round(temperature, 2), 'humidity': np.round(humidity, 2),
                         'price': price, 'is_holiday': holiday})
