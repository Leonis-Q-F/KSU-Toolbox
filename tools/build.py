"""Build and verify a Windows release. No phone access occurs in this script."""
import argparse
import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from release import portable,source_archive,zip_directory

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('dist'))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    tree=ast.parse((root/'src/terminal_ui.py').read_text(encoding='utf-8'))
    version=next(node.value.value for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets))
    if os.name!='nt':raise SystemExit('Windows release builds require Windows x64.')
    subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root/'tests'),'-v'],cwd=root,check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--console','--name','ksu-root','--distpath',str(output/'binary'),'--workpath',str(output/'build'),'--specpath',str(output/'build'),'--paths',str(root/'src'),str(root/'src/cli.py')],cwd=root,check=True)
    package=output/'KSU-Toolbox'
    portable(root,output/'binary/ksu-root.exe',package)
    binary_zip=output/f'KSU-Toolbox-v{version}-windows-x64.zip'
    source_zip=output/f'KSU-Toolbox-v{version}-source.zip'
    zip_directory(package,binary_zip);source_archive(root,source_zip)
    (output/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in (binary_zip,source_zip))+'\n',encoding='utf-8')
    print(f'Built {binary_zip}\nBuilt {source_zip}')

if __name__=='__main__':main()
