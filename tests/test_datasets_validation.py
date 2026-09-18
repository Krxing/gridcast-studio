"""CSV 数据校验规则：拒绝非法输入，不静默补造负荷。"""

import numpy as np
import pandas as pd
import pytest

from backend import datasets


def hourly(rows=300, start='2026-01-01'):
    stamps = pd.date_range(start, periods=rows, freq='h')
    return pd.DataFrame({'timestamp': stamps.strftime('%Y-%m-%d %H:%M:%S'),
                         'load': np.linspace(800, 1200, rows)})


def rejected_with(frame, fragment):
    with pytest.raises(ValueError, match=fragment):
        datasets.validate(frame)


def test_missing_required_columns():
    rejected_with(pd.DataFrame({'timestamp': ['2026-01-01 00:00:00'], 'power': [100]}), 'timestamp 和 load')


def test_negative_load_rejected():
    frame = hourly()
    frame.loc[5, 'load'] = -1
    rejected_with(frame, '不能为负')


def test_time_gap_rejected():
    frame = hourly()
    frame = frame.drop(index=7).reset_index(drop=True)
    rejected_with(frame, '不连续')


def test_fractional_seconds_rejected():
    frame = hourly(3)
    frame.loc[1, 'timestamp'] = '2026-01-01 01:00:00.5'
    rejected_with(frame, '整秒')


def test_mixed_timezone_rejected():
    frame = hourly(3)
    frame.loc[2, 'timestamp'] = '2026-01-01 02:00:00+08:00'
    rejected_with(frame, '时区')


def test_duplicate_timestamps_keep_last_with_warning():
    frame = hourly()
    duplicated = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)
    _, interval, quality = datasets.validate(duplicated)
    assert interval == 60
    assert any('重复' in message for message in quality['warnings'])


def test_consistent_timezone_converted():
    stamps = pd.date_range('2026-01-01', periods=300, freq='h', tz='Asia/Shanghai')
    frame = pd.DataFrame({'timestamp': stamps.strftime('%Y-%m-%d %H:%M:%S%z'), 'load': np.linspace(800, 1200, 300)})
    _, interval, quality = datasets.validate(frame)
    assert interval == 60 and quality['timezone'] == 'Asia/Shanghai'


def test_valid_frame_quality_summary():
    frame = hourly().assign(temperature=21.5, is_holiday=0)
    _, interval, quality = datasets.validate(frame)
    assert interval == 60
    assert quality['unit'] == 'kW' and quality['missing_percent']['temperature'] == 0.0
