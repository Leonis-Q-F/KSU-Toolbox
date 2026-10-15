"""Maintain the pinned, unmodified Windows ADB/Fastboot subset in the repo."""
import argparse
import hashlib
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION='37.0.1'
URL='https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip'
ARCHIVE_SHA256='45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99'
UPSTREAM_FILES=('adb.exe','fastboot.exe','AdbWinApi.dll','AdbWinUsbApi.dll','libwinpthread-1.dll','NOTICE.txt','source.properties')
BUNDLE_FILES=UPSTREAM_FILES+('ORIGIN.json','SHA256SUMS.txt','README.md')

def digest(data):return hashlib.sha256(data).hexdigest()

def verify_bundle(directory):
    directory=Path(directory)
    for name in BUNDLE_FILES:
        path=directory/name
        if not path.is_file() or path.is_symlink():raise ValueError(f'Bundled Platform-Tools missing or linked file: {name}')
    meta=json.loads((directory/'ORIGIN.json').read_text(encoding='utf-8'))
    if meta.get('version')!=VERSION or meta.get('source_url')!=URL or meta.get('archive_sha256')!=ARCHIVE_SHA256:
        raise ValueError('Bundled Platform-Tools provenance does not match the pinned release.')
    if set(meta.get('files',{}))!=set(UPSTREAM_FILES):raise ValueError('Unexpected bundled tool file manifest.')
    for name,expected in meta['files'].items():
        if digest((directory/name).read_bytes())!=expected:raise ValueError(f'Bundled Platform-Tools SHA-256 mismatch: {name}')
    return meta

def install_archive(archive,directory):
    archive=Path(archive);directory=Path(directory)
    if digest(archive.read_bytes())!=ARCHIVE_SHA256:raise ValueError('Official archive SHA-256 does not match the pinned release.')
    directory.mkdir(parents=True,exist_ok=True)
    hashes={}
    with zipfile.ZipFile(archive) as z:
        for name in UPSTREAM_FILES:
            path=directory/name
            if path.is_symlink():raise ValueError('Refusing to overwrite a linked vendor file.')
            entry='platform-tools/'+name
            if z.namelist().count(entry)!=1:raise ValueError('Expected a unique upstream file: '+entry)
            data=z.read(entry);path.write_bytes(data);hashes[name]=digest(data)
    origin={'version':VERSION,'source_url':URL,'archive_sha256':ARCHIVE_SHA256,'files':hashes,'unmodified_upstream_files':True}
    (directory/'ORIGIN.json').write_text(json.dumps(origin,indent=2)+'\n',encoding='utf-8')
    (directory/'README.md').write_text('# Bundled Platform-Tools\n\nWindows ADB/Fastboot '+VERSION+', copied without modification from the pinned Google archive.\n\nSource: '+URL+'\n\nArchive SHA-256: `'+ARCHIVE_SHA256+'`\n\nThe repository and release packages contain only ADB, Fastboot, their runtime DLLs, source.properties and the complete original NOTICE.txt. These components retain their original licenses; the project MIT license does not replace them.\n\nSee NOTICE.txt for original copyrights and license terms. AOSP sources: https://android.googlesource.com/platform/packages/modules/adb/ and https://android.googlesource.com/platform/system/core/ .\n\nMaintainers can reproduce this directory with `python tools/platform_tools.py --archive PATH_TO_OFFICIAL_ZIP`. Without --archive the script fetches the pinned URL and checks the archive hash before writing. Normal tool startup and release builds do not download SDKs.\n',encoding='utf-8')
    lines=[digest((directory/name).read_bytes())+'  '+name for name in BUNDLE_FILES if name!='SHA256SUMS.txt']
    (directory/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return verify_bundle(directory)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,help='Already downloaded pinned official ZIP')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'platform-tools')
    args=parser.parse_args()
    if args.archive:
        install_archive(args.archive,args.output)
    else:
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/'platform-tools.zip'
            with urllib.request.urlopen(URL,timeout=45) as response,archive.open('wb') as file:
                count=0
                while chunk:=response.read(256*1024):
                    count+=len(chunk)
                    if count>32*1024*1024:raise ValueError('Official archive exceeds expected size bound.')
                    file.write(chunk)
            install_archive(archive,args.output)
    print(f'Verified bundled Platform-Tools {VERSION}: {args.output}')

if __name__=='__main__':main()
