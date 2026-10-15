"""Allowlisted release packaging, including a verified ADB/Fastboot subset."""
import hashlib
import importlib.metadata
import shutil
import sys
import zipfile
from pathlib import Path
from platform_tools import BUNDLE_FILES,verify_bundle

ROOT_FILES=['README.md','LICENSE','CHANGELOG.md','CONTRIBUTING.md','SECURITY.md','THIRD_PARTY.md','requirements.txt','requirements-dev.txt','.gitignore','.gitattributes','ksu-root.cmd','build.cmd']
TREES={'src':{'.py'},'tests':{'.py'},'tools':{'.py'},'.github':{'.yml','.yaml'},'docs':{'.md','.png','.svg'}}

def source_files(root):
    root=Path(root).resolve()
    found=[root/name for name in ROOT_FILES if (root/name).is_file()]
    for directory,suffixes in TREES.items():
        found.extend(path for path in (root/directory).rglob('*') if path.is_file() and path.suffix in suffixes and '__pycache__' not in path.parts)
    found.extend(root/'platform-tools'/name for name in BUNDLE_FILES if (root/'platform-tools'/name).is_file())
    return sorted(path for path in set(found) if not path.is_symlink() and path.resolve().is_relative_to(root))

def source_archive(root,destination):
    root=Path(root).resolve()
    if (root/'platform-tools').exists():verify_bundle(root/'platform-tools')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in source_files(root):z.write(path,Path('KSU-Toolbox')/path.relative_to(root))

def licenses(destination):
    directory=Path(destination);directory.mkdir(parents=True,exist_ok=True)
    packages=['requests','urllib3','certifi','charset-normalizer','idna','lz4','rich','markdown-it-py','mdurl','pygments','pyinstaller']
    for package in packages:
        dist=importlib.metadata.distribution(package)
        copied=False
        for relative in dist.files or []:
            if any(word in relative.name.lower() for word in ('license','copying','notice')) and '.dist-info' in str(relative):
                file=Path(dist.locate_file(relative))
                if file.is_file():
                    target=directory/(package+'-'+dist.version);target.mkdir(exist_ok=True)
                    shutil.copy2(file,target/relative.name);copied=True
        if not copied:raise RuntimeError(f'Cannot find license for {package}')
    for name in ('LICENSE_PYTHON.txt','LICENSE.txt','LICENSE'):
        candidate=Path(sys.base_prefix)/name
        if candidate.is_file():
            shutil.copy2(candidate,directory/'Python.txt');break
    else:raise RuntimeError('Cannot find Python runtime license in sys.base_prefix')

def portable(root,binary,directory):
    root=Path(root);directory=Path(directory)
    verify_bundle(root/'platform-tools')
    if directory.exists():raise RuntimeError('Output directory already exists; choose a new --output folder.')
    directory.mkdir(parents=True)
    shutil.copy2(binary,directory/'ksu-root.exe')
    for name in ('README.md','LICENSE','CHANGELOG.md','THIRD_PARTY.md'):
        shutil.copy2(root/name,directory/name)
    # CMD needs CRLF even when checked out with LF on a build runner.
    cmd=(root/'ksu-root.cmd').read_text(encoding='utf-8').replace('\r\n','\n')
    (directory/'ksu-root.cmd').write_bytes(cmd.replace('\n','\r\n').encode('ascii'))
    shutil.copytree(root/'docs',directory/'docs')
    sdk=directory/'platform-tools';sdk.mkdir()
    for name in BUNDLE_FILES:shutil.copy2(root/'platform-tools'/name,sdk/name)
    licenses(directory/'licenses')
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(directory).as_posix() for p in sorted(directory.rglob('*')) if p.is_file()]
    (directory/'SHA256SUMS.txt').write_text('\n'.join(hashes)+'\n',encoding='utf-8')

def zip_directory(directory,destination):
    directory=Path(directory)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(directory.rglob('*')):
            if path.is_file():z.write(path,Path(directory.name)/path.relative_to(directory))
