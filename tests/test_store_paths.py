"""存储路径可移植性：相对路径写入、旧库绝对路径迁移与兼容读取。"""

import importlib
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backend import datasets, store


@pytest.fixture
def relocated_store():
    """把 store 指向独立临时目录，结束后恢复原数据目录。"""
    original = os.environ.get('APP_DATA_DIR')
    temp = Path(tempfile.mkdtemp())
    legacy = temp / 'oldinstall' / '.data'
    (legacy / 'datasets').mkdir(parents=True)
    (legacy / 'models').mkdir(parents=True)
    os.environ['APP_DATA_DIR'] = str(temp / 'runtime')
    yield importlib.reload(store), legacy, temp / 'runtime'
    os.environ['APP_DATA_DIR'] = original
    importlib.reload(store)


def test_new_records_use_relative_paths(relocated_store):
    store.initialize()
    frame = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=300, freq='h'),
                          'load': [1000 + 10 * i for i in range(300)]})
    record = datasets.save_new(frame, '可移植性验证', '园区')
    assert record['path'] == f"datasets/{record['id']}_v1.csv"
    assert not Path(record['path']).is_absolute()
    assert len(datasets.load_frame(record)) == 300


def test_legacy_absolute_paths_are_migrated(relocated_store):
    _, legacy, runtime = relocated_store
    store.initialize()
    store.execute('INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  ('abc', '旧库数据', '园区', 0, 1, 1, 60, 't', 't',
                   str(legacy / 'datasets' / 'abc_v1.csv'), '{}', store.now()))
    store.execute('INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  ('xyz', '旧库模型', 'ensemble', 'abc', 1, 'ready', 24, '{}', '{}',
                   str(legacy / 'models' / 'xyz.joblib'), store.now()))

    # 模拟 .data 整体拷贝到新位置后重启
    (runtime / 'datasets').mkdir(parents=True, exist_ok=True)
    (runtime / 'models').mkdir(parents=True, exist_ok=True)
    (legacy / 'datasets' / 'abc_v1.csv').write_text('timestamp,load\n2026-01-01 00:00:00,100\n')
    (legacy / 'models' / 'xyz.joblib').write_text('x')
    shutil.copy(legacy / 'datasets' / 'abc_v1.csv', runtime / 'datasets' / 'abc_v1.csv')
    shutil.copy(legacy / 'models' / 'xyz.joblib', runtime / 'models' / 'xyz.joblib')
    store.initialize()

    assert store.one("SELECT path FROM datasets WHERE id='abc'")['path'] == 'datasets/abc_v1.csv'
    assert store.one("SELECT artifact FROM models WHERE id='xyz'")['artifact'] == 'models/xyz.joblib'


def test_data_path_supports_unmigrated_legacy_values(relocated_store):
    _, legacy, runtime = relocated_store
    store.initialize()
    (legacy / 'datasets' / 'abc_v1.csv').write_text('timestamp,load\n2026-01-01 00:00:00,100\n')
    (runtime / 'datasets').mkdir(parents=True, exist_ok=True)
    shutil.copy(legacy / 'datasets' / 'abc_v1.csv', runtime / 'datasets' / 'abc_v1.csv')

    relative = store.data_path('datasets/abc_v1.csv')
    legacy_absolute = store.data_path(str(legacy / 'datasets' / 'abc_v1.csv'))
    assert relative == legacy_absolute and relative.exists()
