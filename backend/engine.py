import hashlib
import math
import time
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

from backend import datasets, store

GROUP_NAMES = {'load': '历史负荷', 'calendar': '时间与工作日', 'temperature': '历史温度',
               'humidity': '历史湿度', 'price': '历史电价', 'is_holiday': '历史节假日标记'}


def build_spec(frame, interval, horizon):
    period = 1440 // interval
    window = max(period, min(max(2 * period, 24), 192))
    lags = sorted(set([1, 2, 3, 6, 12, period, 2 * period]))
    lags = [lag for lag in lags if lag <= window]
    exogenous = [column for column in datasets.OPTIONAL if column in frame]
    return {'period': period, 'window': window, 'lags': lags, 'exogenous': exogenous,
            'horizon': horizon, 'interval': interval}


def feature_names(spec):
    names = [f'负荷滞后 {lag} 步' for lag in spec['lags']] + ['周期均值', '周期标准差', '周期最小值', '周期最大值', '近期变化']
    groups = ['load'] * len(names)
    names += ['小时正弦', '小时余弦', '星期正弦', '星期余弦', '周末标记']
    groups += ['calendar'] * 5
    for column in spec['exogenous']:
        names.append(GROUP_NAMES[column])
        groups.append(column)
    return names, groups


def prepare(frame, spec, cutoff=None, defaults=None):
    values = frame['load'].to_numpy(dtype=float)
    if defaults is None:
        defaults = {}
        for column in spec['exogenous']:
            median = frame[column].iloc[:cutoff].median()
            defaults[column] = float(median) if pd.notna(median) else 0.0
    columns = []
    for column in spec['exogenous']:
        if column not in frame:
            raise ValueError(f'该模型需要 {column} 列')
        columns.append(frame[column].ffill().fillna(defaults[column]).to_numpy(dtype=float))
    timestamps = frame['timestamp']
    hours = timestamps.dt.hour.to_numpy() + timestamps.dt.minute.to_numpy() / 60
    weekdays = timestamps.dt.dayofweek.to_numpy()
    sequence = np.column_stack([values] + columns + [np.sin(2 * np.pi * hours / 24), np.cos(2 * np.pi * hours / 24),
                                                      np.sin(2 * np.pi * weekdays / 7), np.cos(2 * np.pi * weekdays / 7)])
    return values, columns, sequence, defaults


def features(frame, spec, origins, defaults):
    values, exogenous, sequence, _ = prepare(frame, spec, defaults=defaults)
    input_rows, baseline_rows, sequence_rows = [], [], []
    for origin in origins:
        recent = values[max(0, origin - spec['period']):origin]
        stamp = frame['timestamp'].iloc[origin - 1] + pd.Timedelta(minutes=spec['interval'])
        hour = stamp.hour + stamp.minute / 60
        row = [values[origin - lag] for lag in spec['lags']]
        row += [recent.mean(), recent.std(), recent.min(), recent.max(), values[origin - 1] - values[origin - min(6, spec['window'])]]
        row += [math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24),
                math.sin(2 * math.pi * stamp.dayofweek / 7), math.cos(2 * math.pi * stamp.dayofweek / 7), float(stamp.dayofweek >= 5)]
        row += [column[origin - 1] for column in exogenous]
        input_rows.append(row)
        baseline_rows.append(np.resize(values[origin - spec['period']:origin], spec['horizon']))
        sequence_rows.append(sequence[origin - spec['window']:origin])
    return np.asarray(input_rows), np.asarray(baseline_rows), np.asarray(sequence_rows)


def infer(bundle, frame, origins):
    inputs, baseline, sequence = features(frame, bundle['spec'], origins, bundle['defaults'])
    if bundle['kind'] == 'ensemble':
        draws = np.stack([tree.predict(inputs) for tree in bundle['engine'].estimators_])
        point = baseline + draws.mean(axis=0)
        scale = draws.std(axis=0)
    elif bundle['kind'] == 'hybrid':
        from backend.hybrid import predict
        residual, scale = predict(bundle['engine'], (sequence - bundle['sequence_mean']) / bundle['sequence_std'])
        point = baseline + residual * bundle['target_scale']
        scale *= bundle['target_scale']
    else:
        point = baseline
        scale = np.ones_like(point) * bundle['noise_floor']
    return np.maximum(point, 0), np.maximum(scale, bundle['noise_floor']), baseline


def bounds(bundle, point, scale, confidence):
    scores = np.abs(bundle['calibration_scores']).ravel()
    probability = min(1.0, math.ceil((len(scores) + 1) * confidence) / len(scores))
    quantile = float(np.quantile(scores, probability, method='higher'))
    width = quantile * scale
    return np.maximum(0, point - width), point + width


def metrics(actual, point, lower=None, upper=None, confidence=.95):
    actual, point = np.asarray(actual), np.asarray(point)
    error = point - actual
    nonzero = np.abs(actual) > 1e-6
    result = {'mae': float(np.abs(error).mean()), 'rmse': float(np.sqrt((error ** 2).mean())),
              'mape': float((np.abs(error[nonzero] / actual[nonzero])).mean() * 100) if nonzero.any() else None,
              'wape': float(np.abs(error).sum() / np.abs(actual).sum() * 100) if np.abs(actual).sum() > 1e-6 else None,
              'points': int(actual.size), 'mape_excluded_zeros': int((~nonzero).sum())}
    if lower is not None:
        result.update({'coverage': float(((actual >= lower) & (actual <= upper)).mean() * 100),
                       'mean_width': float((upper - lower).mean()),
                       'interval_score': float(((upper - lower) + 2 / (1 - confidence) *
                                                (np.maximum(lower - actual, 0) + np.maximum(actual - upper, 0))).mean())})
    return {key: round(value, 4) if isinstance(value, float) else value for key, value in result.items()}


def train(model, snapshot, job_id):
    frame = datasets.load_frame(snapshot)
    horizon = model['horizon']
    spec = build_spec(frame, snapshot['interval_minutes'], horizon)
    count = len(frame)
    train_end, validation_end, calibration_end = int(count * .60), int(count * .75), int(count * .875)
    if train_end < spec['window'] + horizon + 32 or min(validation_end - train_end, calibration_end - validation_end, count - calibration_end) < 2 * horizon:
        raise ValueError(f'数据不足。当前 {count} 行，建议至少 {max(20 * horizon, 4 * spec["window"])} 行，或缩短预测步数')
    train_origins = np.arange(spec['window'], train_end - horizon + 1, max(1, spec['period'] // 8))
    if len(train_origins) > 2500:
        train_origins = train_origins[np.linspace(0, len(train_origins) - 1, 2500, dtype=int)]
    validation_origins = np.arange(train_end, validation_end - horizon + 1, horizon)
    calibration_origins = np.arange(validation_end, calibration_end - horizon + 1, horizon)
    test_origins = np.arange(calibration_end, count - horizon + 1, horizon)
    _, _, raw_sequence, defaults = prepare(frame, spec, cutoff=train_end)
    train_input, train_baseline, train_sequence = features(frame, spec, train_origins, defaults)
    val_input, val_baseline, val_sequence = features(frame, spec, validation_origins, defaults)
    values = frame['load'].to_numpy()
    train_target = np.stack([values[origin:origin + horizon] for origin in train_origins])
    val_target = np.stack([values[origin:origin + horizon] for origin in validation_origins])
    names, groups = feature_names(spec)
    target_scale = max(float(values[:train_end].std()), 1.0)
    bundle = {'kind': model['kind'], 'spec': spec, 'defaults': defaults, 'feature_names': names,
              'feature_groups': groups, 'reference_input': np.median(train_input, axis=0),
              'noise_floor': max(target_scale * .03, .1), 'target_scale': target_scale,
              'calibration_end': calibration_end, 'train_end': train_end, 'snapshot_rows': count,
              'sequence_mean': raw_sequence[:train_end].mean(axis=0),
              'sequence_std': np.maximum(raw_sequence[:train_end].std(axis=0), 1e-3)}
    store.progress(job_id, 12, f'按时间划分训练 / 验证 / 校准 / 测试；训练样本 {len(train_origins)} 个')
    history = []
    if model['kind'] == 'ensemble':
        forest = ExtraTreesRegressor(n_estimators=16, max_depth=14, min_samples_leaf=2,
                                     random_state=42, n_jobs=2, bootstrap=True, warm_start=True)
        for tree_count in [16, 32, 64]:
            forest.set_params(n_estimators=tree_count)
            forest.fit(train_input, train_target - train_baseline)
            history.append({'step': tree_count,
                            'train_loss': float(np.mean((forest.predict(train_input) + train_baseline - train_target) ** 2)),
                            'val_loss': float(np.mean((forest.predict(val_input) + val_baseline - val_target) ** 2))})
            store.progress(job_id, 15 + int(tree_count / 64 * 48), f'已训练 {tree_count} 棵树，验证 RMSE {math.sqrt(history[-1]["val_loss"]):.2f} kW')
        bundle['engine'] = forest
    elif model['kind'] == 'hybrid':
        from backend.hybrid import fit
        epochs = model['params'].get('epochs', 12)
        def callback(epoch, record):
            store.progress(job_id, 15 + int(epoch / epochs * 50), f'Epoch {epoch}/{epochs} · 验证归一化 MSE {record["val_loss"]:.4f}')
        bundle['engine'], history = fit((train_sequence - bundle['sequence_mean']) / bundle['sequence_std'],
                                        (train_target - train_baseline) / target_scale,
                                        (val_sequence - bundle['sequence_mean']) / bundle['sequence_std'],
                                        (val_target - val_baseline) / target_scale, epochs, callback)
    else:
        bundle['engine'] = None
    store.progress(job_id, 72, '使用独立校准段估计区间尺度，不使用测试标签调整模型')
    cal_point, cal_scale, _ = infer(bundle, frame, calibration_origins)
    cal_actual = np.stack([values[origin:origin + horizon] for origin in calibration_origins])
    bundle['calibration_scores'] = (cal_actual - cal_point) / cal_scale
    test_point, test_scale, baseline = infer(bundle, frame, test_origins)
    test_actual = np.stack([values[origin:origin + horizon] for origin in test_origins])
    lower, upper = bounds(bundle, test_point, test_scale, .95)
    evaluation = metrics(test_actual, test_point, lower, upper)
    baseline_metrics = metrics(test_actual, baseline)
    generator = np.random.default_rng(42)
    scores = generator.choice(bundle['calibration_scores'].ravel(), size=(48,) + test_point.shape)
    draws = np.maximum(0, test_point[None] + scores * test_scale[None])
    ordered = np.sort(draws, axis=0)
    weights = (2 * np.arange(1, 49) - 49).reshape(48, 1, 1)
    crps = np.mean(np.abs(draws - test_actual[None]), axis=0) - np.sum(weights * ordered, axis=0) / 48 ** 2
    evaluation.update({'crps': round(float(crps.mean()), 4), 'baseline': baseline_metrics,
                       'improvement': round((1 - evaluation['mae'] / max(baseline_metrics['mae'], 1e-6)) * 100, 2),
                       'confidence': .95, 'test_windows': len(test_origins), 'calibration_windows': len(calibration_origins),
                       'test_start': frame['timestamp'].iloc[int(test_origins[0])].isoformat(),
                       'test_end': frame['timestamp'].iloc[int(test_origins[-1]) + horizon - 1].isoformat(),
                       'history': history, 'split_counts': {'train': train_end, 'validation': validation_end - train_end,
                                                          'calibration': calibration_end - validation_end, 'test': count - calibration_end},
                       'horizon_mae': np.abs(test_point - test_actual).mean(axis=0).round(3).tolist(),
                       'interval_method': '独立校准段标准化残差经验区间；时序相关下无分布无关覆盖保证',
                       'crps_method': '校准残差经验预测分布，48 次可复现抽样估计',
                       'is_demo': bool(snapshot['is_demo'])})
    evaluation['evaluation_key'] = hashlib.sha256(f'{snapshot["id"]}:{snapshot["version"]}:{horizon}:{evaluation["test_start"]}:{evaluation["test_end"]}'.encode()).hexdigest()[:16]
    previous_id = model['params'].get('previous_model_id')
    if previous_id:
        previous = store.one('SELECT * FROM models WHERE id=?', (previous_id,))
        if previous and previous['artifact'] and previous['horizon'] == horizon:
            old_point, _, _ = infer(load_bundle(store.data_path(previous['artifact'])), frame, test_origins)
            old_metrics = metrics(test_actual, old_point)
            evaluation['candidate_review'] = {'previous_model_id': previous_id, 'previous_mae': old_metrics['mae'],
                                              'candidate_mae': evaluation['mae'], 'same_window': True,
                                              'recommended': evaluation['mae'] < old_metrics['mae'],
                                              'automatic_release': False}
    bundle['metrics'] = evaluation
    artifact = store.DATA / 'models' / f'{model["id"]}.joblib'
    joblib.dump(bundle, artifact, compress=3)
    store.execute('UPDATE models SET status=?, artifact=?, metrics=? WHERE id=?',
                  ('ready', f'models/{artifact.name}', store.encode(evaluation), model['id']))
    store.progress(job_id, 96, f'测试完成：MAE {evaluation["mae"]:.2f} kW；等待人工上线')
    store.event('模型训练完成', f'{model["name"]} · MAE {evaluation["mae"]:.2f} kW')
    return {'model_id': model['id']}


@lru_cache(maxsize=8)
def load_bundle(path):
    return joblib.load(path)


def explanation(bundle, frame, origin, point):
    spec = bundle['spec']
    inputs, baseline, sequence = features(frame, spec, [origin], bundle['defaults'])
    contributions = []
    if bundle['kind'] == 'ensemble':
        for group in dict.fromkeys(bundle['feature_groups']):
            changed = inputs.copy()
            indices = [index for index, value in enumerate(bundle['feature_groups']) if value == group]
            changed[:, indices] = bundle['reference_input'][indices]
            altered = np.maximum(0, baseline + bundle['engine'].predict(changed))
            contributions.append({'name': GROUP_NAMES[group], 'value': round(float((point - altered).mean()), 3)})
        method = '分组扰动敏感度：将一组工程特征替换为训练中位数，保持季节基线不变；不是 SHAP，也不是因果效应'
    elif bundle['kind'] == 'hybrid':
        import torch
        network = bundle['engine']
        network.eval()
        channels = ['load'] + spec['exogenous'] + ['calendar'] * 4
        normalized = (sequence - bundle['sequence_mean']) / bundle['sequence_std']
        for group in dict.fromkeys(channels):
            changed = normalized.copy()
            indices = [index for index, value in enumerate(channels) if value == group]
            changed[:, :, indices] = 0
            with torch.no_grad():
                altered = baseline + network(torch.from_numpy(changed.astype(np.float32))).numpy() * bundle['target_scale']
            contributions.append({'name': GROUP_NAMES[group], 'value': round(float((point - np.maximum(altered, 0)).mean()), 3)})
        method = '历史输入通道遮蔽敏感度：替换为训练均值，保持季节基线不变；非因果解释，各项不要求相加等于预测值'
    else:
        contributions = [{'name': '上一周期同一时刻负荷', 'value': 0.0}]
        method = '季节朴素基线：重复最近一个完整周期的负荷，不使用外部特征'
    return {'method': method, 'items': sorted(contributions, key=lambda item: abs(item['value']), reverse=True)}


def forecast(model, snapshot, mode, confidence):
    started = time.perf_counter()
    bundle = load_bundle(store.data_path(model['artifact']))
    frame = datasets.load_frame(snapshot)
    if snapshot['interval_minutes'] != bundle['spec']['interval']:
        raise ValueError('数据采样间隔与模型不一致')
    origin = len(frame) if mode == 'future' else len(frame) - model['horizon']
    if origin < bundle['calibration_end']:
        raise ValueError('回测目标必须位于训练和校准之后')
    point, scale, _ = infer(bundle, frame, [origin])
    lower, upper = bounds(bundle, point, scale, confidence)
    attribution = explanation(bundle, frame, origin, point)
    stamps = pd.date_range(frame['timestamp'].iloc[origin - 1] + pd.Timedelta(minutes=snapshot['interval_minutes']),
                           periods=model['horizon'], freq=f'{snapshot["interval_minutes"]}min')
    rows = [{'timestamp': stamp.isoformat(), 'point': round(float(point[0, index]), 3),
             'lower': round(float(lower[0, index]), 3), 'upper': round(float(upper[0, index]), 3)}
            for index, stamp in enumerate(stamps)]
    peak_index = int(point.argmax())
    result = {'series': rows, 'history': datasets.series(frame.iloc[max(0, origin - 2 * bundle['spec']['period']):origin]),
              'explanation': attribution, 'peak': round(float(point.max()), 2), 'peak_time': stamps[peak_index].isoformat(),
              'valley': round(float(point.min()), 2), 'energy_kwh': round(float(point.sum() * snapshot['interval_minutes'] / 60), 2),
              'load_factor': round(float(point.mean() / max(point.max(), 1e-6) * 100), 2),
              'mean_width': round(float((upper - lower).mean()), 2), 'interval_minutes': snapshot['interval_minutes'],
              'is_demo': bool(snapshot['is_demo']), 'inference_ms': round((time.perf_counter() - started) * 1000, 1),
              'model_name': model['name'], 'dataset_name': snapshot['name'],
              'feature_policy': '仅使用预测起点之前的负荷与外部变量，加上已知时间特征；未使用未来实测气象',
              'interval_method': bundle['metrics']['interval_method']}
    forecast_id = store.uid()
    store.execute('INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?,?)',
                  (forecast_id, model['id'], snapshot['id'], snapshot['version'], mode, confidence,
                   frame['timestamp'].iloc[origin - 1].isoformat(), store.encode(result), store.now()))
    store.event('预测已完成', f'{snapshot["name"]} · {model["horizon"]} 步 · {confidence:.0%} 预测区间')
    return {'forecast_id': forecast_id}


def enrich_forecast(record):
    snapshot = datasets.get_dataset(record['dataset_id'])
    frame = datasets.load_frame(snapshot)
    actual_map = dict(zip(frame['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S'), frame['load']))
    rows = record['result']['series']
    for row in rows:
        row['actual'] = float(actual_map[row['timestamp']]) if row['timestamp'] in actual_map else None
    available = [row for row in rows if row['actual'] is not None]
    record['result']['observed_points'] = len(available)
    record['result']['evaluation_status'] = 'complete' if len(available) == len(rows) else 'partial' if available else 'pending'
    record['result']['actual_metrics'] = metrics(np.array([row['actual'] for row in available]),
                                               np.array([row['point'] for row in available]),
                                               np.array([row['lower'] for row in available]),
                                               np.array([row['upper'] for row in available]), record['confidence']) if available else None
    return record
