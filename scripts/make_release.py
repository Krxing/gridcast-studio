"""生成交付 zip：git 跟踪的源码 + 预构建前端 + 需求文档。

用法（仓库根目录）：
    python scripts/make_release.py

产物：dist-release/gridcast-<日期>-<短SHA>.zip 及对应 .sha256。
zip 顶层为单一目录 gridcast-<日期>-<短SHA>/，接收方解压后按
docs/部署手册.md 操作即可，无需 Node.js（前端已预构建）。
"""

import hashlib
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRA_FILES = [
    Path('frontend/dist'),                    # 预构建前端（gitignore 中）
    Path('用电量预测原型系统需求分析.docx'),   # 需求文档（*.docx 被 ignore）
]


def run(command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, shell=(sys.platform == 'win32'))
    if result.returncode != 0:
        sys.exit(f'命令失败 {" ".join(command)}\n{result.stderr.strip()}')
    return result.stdout.strip()


def main():
    if run(['git', 'status', '--porcelain']):
        sys.exit('工作区有未提交改动，请先提交或暂存（保证交付内容与版本库一致）。')

    sha = run(['git', 'rev-parse', '--short', 'HEAD'])
    version = f'{date.today():%Y%m%d}-{sha}'
    name = f'gridcast-{version}'

    for extra in EXTRA_FILES:
        if not (ROOT / extra).exists():
            sys.exit(f'缺少交付所需文件：{extra}。请先构建前端（frontend: npm run build）。')

    output_dir = ROOT / 'dist-release'
    output_dir.mkdir(exist_ok=True)
    zip_path = output_dir / f'{name}.zip'

    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp)
        archive_bytes = subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, capture_output=True).stdout
        import io
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
            archive.extractall(stage, filter='data')
        (stage / name).mkdir()
        for item in stage.iterdir():
            if item.name not in (name, 'source.tar'):
                item.rename(stage / name / item.name)
        for extra in EXTRA_FILES:
            source = ROOT / extra
            target = stage / name / extra
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                for file in source.rglob('*'):
                    if file.is_file():
                        destination = target / file.relative_to(source)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(file.read_bytes())
            else:
                target.write_bytes(source.read_bytes())

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for file in sorted((stage / name).rglob('*')):
                if file.is_file():
                    bundle.write(file, file.relative_to(stage))

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (output_dir / f'{name}.zip.sha256').write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
    print(f'已生成 {zip_path}')
    print(f'SHA256 {digest}')
    print('交付说明随包内 docs/部署手册.md。')


if __name__ == '__main__':
    main()
