"""Read-only firmware extraction. Never executes or extracts archive paths."""
import bz2
import hashlib
import io
import lzma
import re
import struct
import tarfile
import zipfile
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ToolError(Exception):
    pass

MAX_IMAGE = 128 * 1024 * 1024
MAX_META = 8 * 1024 * 1024

def require(condition, message):
    if not condition:
        raise ToolError(message)

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def parse_metadata(text):
    result = {}
    for line in text.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            require(key.strip() not in result, '包内元数据字段重复。')
            result[key.strip()] = value.strip()
    return result

def match_ota(meta, phone, source):
    require(meta.get('pre-device') == phone['device'], '卡刷包机型与手机不一致。')
    version = meta.get('post-build-incremental', '')
    allowed = {phone.get(k, '') for k in ('version', 'internal', 'system_internal')} - {''}
    require(version and version in allowed, '卡刷包构建号与手机当前系统不一致。')
    require(meta.get('post-security-patch-level') == phone.get('security_patch') and phone.get('security_patch'), '安全补丁级别不一致或缺失。')
    require(meta.get('post-sdk-level') == phone.get('sdk') and phone.get('sdk'), 'Android SDK 版本不一致或缺失。')
    names = re.findall(r'OS\d+\.\d+\.\d+\.\d+\.[A-Z0-9]+', unquote(urlparse(source).path))
    require(not names or all(n == phone['version'] for n in names), '包名中的系统版本与手机不一致。')

def match_fastboot(meta, phone):
    require(meta.get('device') == phone['device'], '线刷包 misc.txt 中的机型与手机不一致。')
    version = meta.get('build_number') or meta.get('mi_os_build_version')
    require(version and version == phone['version'], '线刷包版本与手机当前系统不一致。')
    if meta.get('mi_os_build_version'):
        require(meta['mi_os_build_version'] == phone['version'], '线刷包版本字段互相矛盾。')

class RemoteFile(io.RawIOBase):
    """Bounded HTTP range reader; rejects ignored ranges before reading the body."""
    BLOCK = 256 * 1024
    def __init__(self, url):
        super().__init__()
        require(urlparse(url).scheme == 'https', '远程卡刷包只支持 HTTPS 链接。')
        self.session = requests.Session()
        self.session.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=.5, status_forcelist=[429,500,502,503,504])))
        self.url = url
        self.pos = 0
        self.cache = OrderedDict()
        self.downloaded = 0
        with self.session.get(url, headers={'Range':'bytes=0-0','Accept-Encoding':'identity'}, stream=True, timeout=(15,40)) as r:
            require(r.status_code == 206, '服务器不支持分段读取。请完整下载 ZIP，再选择本地文件。')
            match = re.fullmatch(r'bytes 0-0/(\d+)', r.headers.get('Content-Range',''))
            require(match, '服务器的 Content-Range 不合法。')
            self.size = int(match[1])
            self.etag = r.headers.get('ETag')
            self.modified = r.headers.get('Last-Modified')
            require((self.etag and not self.etag.startswith('W/')) or self.modified, '远程文件缺少稳定版本标记，请改用本地 ZIP。')
            require(r.raw.read(2) == b'P', '链接不是标准 ZIP 卡刷包。')
        self.downloaded = 1

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, offset, whence=0):
        require(whence in (0,1,2), '无效的读取位置。')
        dest = offset if whence == 0 else self.pos+offset if whence == 1 else self.size+offset
        require(0 <= dest <= self.size, 'ZIP 中的读取偏移越界。')
        self.pos = dest
        return dest

    def fetch(self, start, length):
        require(0 <= length <= MAX_IMAGE and 0 <= start and start+length <= self.size, '远程数据范围越界或过大。')
        if not length: return b''
        end = start+length-1
        headers = {'Range':f'bytes={start}-{end}', 'Accept-Encoding':'identity'}
        if self.etag and not self.etag.startswith('W/'):
            headers['If-Match'] = self.etag
        else:
            headers['If-Unmodified-Since'] = self.modified
        with self.session.get(self.url, headers=headers, stream=True, timeout=(15,45)) as r:
            require(r.status_code == 206, f'分段下载失败（HTTP {r.status_code}）。')
            require(r.headers.get('Content-Range') == f'bytes {start}-{end}/{self.size}', '服务器返回了错误的数据范围。')
            if self.etag:
                require(r.headers.get('ETag') == self.etag, '下载期间远程包发生变化。')
            data = r.raw.read(length+1)
            require(len(data) == length, '分段数据不完整。')
        self.downloaded += length
        return data

    def read(self, length=-1):
        length = min(self.size-self.pos, length if length >= 0 else self.size-self.pos)
        require(length <= MAX_IMAGE, '单次读取数据过大。请改用本地完整 ZIP。')
        chunks = []
        while length:
            base = self.pos // self.BLOCK * self.BLOCK
            if base not in self.cache:
                self.cache[base] = self.fetch(base, min(self.BLOCK,self.size-base))
                if len(self.cache) > 32:
                    self.cache.popitem(last=False)
            block = self.cache[base]
            self.cache.move_to_end(base)
            off = self.pos-base
            chunk = block[off:off+length]
            require(chunk, '远程文件提前结束。')
            chunks.append(chunk)
            self.pos += len(chunk)
            length -= len(chunk)
        return b''.join(chunks)

    def close(self):
        self.session.close()
        super().close()

def protobuf(data):
    pos = 0
    def varint():
        nonlocal pos
        value = 0
        for shift in range(0,70,7):
            require(pos < len(data), '截断的 payload 元数据。')
            b = data[pos]; pos += 1
            value |= (b & 127) << shift
            if b < 128: return value
        raise ToolError('payload 数值字段过长。')
    result = {}
    while pos < len(data):
        key = varint(); tag, wire = key >> 3, key & 7
        require(tag > 0, 'payload 字段编号无效。')
        if wire == 0:
            value = varint()
        elif wire in (1,2,5):
            size = varint() if wire == 2 else 8 if wire == 1 else 4
            require(pos+size <= len(data), 'payload 字段截断。')
            value = data[pos:pos+size]; pos += size
        else:
            raise ToolError('不支持的 payload 字段格式。')
        result.setdefault(tag,[]).append(value)
    return result

def limited_decompress(data, kind, limit):
    if kind == 0:
        result = data
    elif kind in (1,8):
        decoder = bz2.BZ2Decompressor() if kind == 1 else lzma.LZMADecompressor(memlimit=256*1024*1024)
        result = decoder.decompress(data,max_length=limit+1)
        require(decoder.eof and not decoder.unused_data, '镜像压缩数据不完整或包含多余数据。')
    else:
        raise ToolError(f'不支持的 payload 操作类型 {kind}；未生成可刷写镜像。')
    require(len(result) == limit, '解压后的数据大小与分区记录不一致。')
    return result

def extract_ota(source, phone, log=print, on_verified=None):
    stream = RemoteFile(source) if source.lower().startswith(('https://','http://')) else open(source,'rb')
    try:
        with zipfile.ZipFile(stream) as archive:
            require(archive.namelist().count('META-INF/com/android/metadata') == 1 and archive.namelist().count('payload.bin') == 1, '卡刷包必须包含唯一的 metadata 和 payload.bin。')
            entry = archive.getinfo('META-INF/com/android/metadata')
            require(entry.file_size <= MAX_META, '卡刷包元数据过大。')
            meta = parse_metadata(archive.read(entry).decode('utf-8'))
            match_ota(meta,phone,source)
            if on_verified:on_verified()
            log('机型、构建号、安全补丁和 Android 版本匹配。')
            entry = archive.getinfo('payload.bin')
            require(entry.compress_type == zipfile.ZIP_STORED, '只支持 ZIP 中未再次压缩的 payload.bin。')
            stream.seek(entry.header_offset)
            local = stream.read(30)
            require(len(local) == 30 and local[:4] == b'PK\x03\x04', 'payload ZIP 头不合法。')
            nl, el = struct.unpack_from('<HH',local,26)
            start = entry.header_offset+30+nl+el
            def read_at(offset,size):
                require(0 <= offset and 0 <= size <= MAX_IMAGE and offset+size <= entry.file_size, 'payload 内部范围越界。')
                stream.seek(start+offset)
                data = stream.read(size)
                require(len(data) == size, 'payload 提前结束。')
                return data
            head = read_at(0,24)
            magic,version,ml,sl = struct.unpack('>4sQQI',head)
            require(magic == b'CrAU' and version == 2 and ml <= MAX_META and sl <= MAX_META, '不支持此 payload 格式。')
            manifest = protobuf(read_at(24,ml))
            require(manifest.get(12,[0])[0] == 0, '这是增量 OTA，请使用当前版本的完整卡刷包。')
            parts = [protobuf(p) for p in manifest.get(13,[])]
            parts = [p for p in parts if p.get(1) == [b'init_boot']]
            require(len(parts) == 1, '包内没有唯一的 init_boot 分区；此设备不在工具支持范围内。')
            part = parts[0]
            info = protobuf(part[7][0])
            size, expected = info[1][0], info[2][0]
            block = manifest.get(3,[4096])[0]
            require(0 < size <= MAX_IMAGE and len(expected) == 32 and block == 4096 and size % block == 0, '分区尺寸或哈希不合法。')
            result = bytearray(size)
            coverage = set()
            ops = part.get(8,[])
            for index,raw in enumerate(ops):
                op = protobuf(raw); kind = op[1][0]
                extents = [protobuf(e) for e in op.get(6,[])]
                count = sum(e[2][0] for e in extents)
                require(0 < count <= size//block and kind in (0,1,6,8), f'不支持的操作或范围：{kind}。')
                for ext in extents:
                    begin, n = ext[1][0], ext[2][0]
                    require(n > 0 and begin+n <= size//block, '目标分区范围越界。')
                    blocks = set(range(begin,begin+n))
                    require(not coverage.intersection(blocks), '分区操作范围重叠。')
                    coverage.update(blocks)
                if kind == 6:
                    decoded = bytes(count*block)
                else:
                    blob = read_at(24+ml+sl+op.get(2,[0])[0],op[3][0])
                    require(op.get(8) == [hashlib.sha256(blob).digest()], '镜像数据块 SHA-256 校验失败。')
                    decoded = limited_decompress(blob,kind,count*block)
                cursor = 0
                for ext in extents:
                    begin, length = ext[1][0]*block, ext[2][0]*block
                    result[begin:begin+length] = decoded[cursor:cursor+length]
                    cursor += length
                log(f'提取 init_boot：{index+1}/{len(ops)}')
            require(len(coverage) == size//block and hashlib.sha256(result).digest() == expected, '完整镜像 SHA-256 或覆盖范围校验失败。')
            return bytes(result), {'kind':'ota','metadata':meta,'sha256':expected.hex(),'manifest_hash_verified':True,'package_signature_verified':False,'downloaded_bytes':getattr(stream,'downloaded',None)}
    finally:
        stream.close()

def extract_fastboot(source, phone, log=print, on_verified=None):
    require(not source.lower().startswith(('https://','http://')), '线刷包请先下载到电脑，或选择已解压的文件夹。')
    path = Path(source)
    meta_raw = image = None
    if path.is_dir():
        require(not path.is_symlink(), '请选择实际文件夹。')
        if path.name.lower() == 'images': path = path.parent
        pairs = [(p,p.parent/'images/init_boot.img') for p in path.glob('misc.txt')]
        pairs += [(p,p.parent/'images/init_boot.img') for p in path.glob('*/misc.txt')]
        pairs = [(m,i) for m,i in pairs if i.is_file()]
        require(len(pairs) == 1, '文件夹必须包含唯一的 misc.txt 和 images/init_boot.img。')
        m,i = pairs[0]
        require(m.resolve().is_relative_to(path.resolve()) and i.resolve().is_relative_to(path.resolve()), '镜像路径指向了包目录以外。')
        require(m.stat().st_size <= MAX_META and i.stat().st_size <= MAX_IMAGE, '包内文件过大。')
        meta_raw = m.read_bytes(); image = i.read_bytes()
    else:
        require(path.is_file(), '找不到线刷包。')
        found_meta, found_image = [], []
        def consume(name, size, reader):
            parts = PurePosixPath(name.replace('\\','/')).parts
            if not parts or '..' in parts or name.startswith(('/', '\\')): return
            wanted_meta = parts[-1] == 'misc.txt'
            wanted_image = len(parts) >= 2 and parts[-2:] == ('images','init_boot.img')
            if wanted_meta or wanted_image:
                require(0 < size <= (MAX_META if wanted_meta else MAX_IMAGE), '包内目标文件尺寸无效。')
                data = reader()
                require(len(data) == size, '线刷包目标文件读取不完整。')
                (found_meta if wanted_meta else found_image).append((PurePosixPath(*parts[:-1 if wanted_meta else -2]),data))
        log('正在扫描本地线刷包；TGZ 需要顺序解压扫描，可能耗时数分钟。')
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for entry in z.infolist():
                    if not entry.is_dir():consume(entry.filename,entry.file_size,lambda e=entry:z.read(e))
        else:
            with tarfile.open(path,mode='r|*') as tar:
                for entry in tar:
                    if entry.isfile():consume(entry.name,entry.size,lambda e=entry:tar.extractfile(e).read(e.size+1))
        require(len(found_meta) == len(found_image) == 1, '线刷包必须包含唯一的 misc.txt 和 images/init_boot.img。')
        require(found_meta[0][0] == found_image[0][0], '线刷包元数据与镜像不属于同一目录。')
        meta_raw, image = found_meta[0][1], found_image[0][1]
    meta = parse_metadata(meta_raw.decode('utf-8-sig'))
    match_fastboot(meta,phone)
    if on_verified:on_verified()
    return image, {'kind':'fastboot','metadata':meta,'sha256':sha256(image),'manifest_hash_verified':False,'package_signature_verified':False}
