"""Validate the known KernelSU LKM ramdisk layout before permitting flash."""
import gzip
import hashlib
import io
import re
import struct

import lz4.block
import lz4.frame

from firmware import ToolError, require, MAX_IMAGE

MAX_RAMDISK = 64*1024*1024

def header(image):
    require(4096 <= len(image) <= MAX_IMAGE and image[:8] == b'ANDROID!', '不是有效的 Android 启动镜像。')
    kernel,ramdisk,osver,size = struct.unpack_from('<4I',image,8)
    version = struct.unpack_from('<I',image,40)[0]
    require(kernel == 0 and version == 4 and size == 1584, '仅支持无内核的 v4 init_boot 镜像；不会自动改刷 boot。')
    require(0 < ramdisk <= MAX_RAMDISK and 4096+ramdisk <= len(image), 'init_boot ramdisk 大小不合法。')
    return ramdisk

def ramdisk(image):
    size = header(image)
    raw = image[4096:4096+size]
    if raw.startswith(b'\x02\x21\x4c\x18'):
        pos = 4; chunks = []; total = 0
        while pos < len(raw):
            require(pos+4 <= len(raw), 'LZ4 数据截断。')
            length = struct.unpack_from('<I',raw,pos)[0]; pos += 4
            if length == 0:
                require(pos == len(raw), 'LZ4 尾部有未知数据。')
                break
            require(pos+length <= len(raw), 'LZ4 数据块截断。')
            block = lz4.block.decompress(raw[pos:pos+length],uncompressed_size=8*1024*1024)
            pos += length; total += len(block)
            require(total <= MAX_RAMDISK, '解压的 ramdisk 过大。')
            chunks.append(block)
        data = b''.join(chunks)
    elif raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as g:
            data = g.read(MAX_RAMDISK+1)
    elif raw.startswith(b'\x04\x22\x4d\x18'):
        decoder = lz4.frame.LZ4FrameDecompressor()
        data = decoder.decompress(raw,max_length=MAX_RAMDISK+1)
        require(decoder.eof and not decoder.unused_data, 'LZ4 frame 不完整、过大或含额外压缩流。')
    elif raw.startswith((b'070701',b'070702')):
        data = raw
    else:
        raise ToolError('不支持此 ramdisk 压缩格式，停止刷写。')
    require(len(data) <= MAX_RAMDISK, '解压的 ramdisk 过大。')
    return cpio(data)

def cpio(data):
    pos = 0; entries = {}
    while pos+110 <= len(data):
        h = data[pos:pos+110]
        require(h[:6] in (b'070701',b'070702'), '无效的 CPIO 头。')
        nums = [int(h[i:i+8],16) for i in range(6,110,8)]
        size,namesize = nums[6],nums[11]
        require(0 < namesize <= 4096 and pos+110+namesize <= len(data), 'CPIO 文件名越界。')
        name_bytes = data[pos+110:pos+110+namesize]
        require(name_bytes[-1:] == b'\0', 'CPIO 文件名未终止。')
        name = name_bytes[:-1].decode('utf-8')
        pos = (pos+110+namesize+3)&~3
        if name == 'TRAILER!!!':
            require(size == 0 and not any(data[pos:]), 'CPIO 尾部含有额外内容或第二个归档。')
            return entries
        require(name not in entries and pos+size <= len(data), 'CPIO 重复文件或数据越界。')
        kind = nums[1] & 0o170000
        require(kind == 0o040000 or nums[4] == 1, '不支持含非目录硬链接的 ramdisk。')
        # Include rdev fields: changing a preserved device node must be detected.
        entries[name] = (nums[1],nums[2],nums[3],data[pos:pos+size],nums[4],nums[9],nums[10])
        pos = (pos+size+3)&~3
    raise ToolError('CPIO 缺少结束标记。')

def arm64_elf(data):
    return len(data)>20 and data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,18)[0] == 183

def verify_patch(original, patched, kernel):
    header(original); header(patched)
    require(len(original) == len(patched) and original != patched, '修补镜像大小不符或根本没有修改。')
    require(original[:12] == patched[:12] and original[16:4096] == patched[16:4096], '修补修改了预期之外的启动头内容。')
    old,new = ramdisk(original),ramdisk(patched)
    require('kernelsu.ko' not in old and 'stock_image.sha1' not in old, '选中的原厂镜像已被修补。')
    required = {'init','init.real','kernelsu.ko','stock_image.sha1'}
    require(required.issubset(new) and 'init' in old, '修补镜像不是当前支持的 KernelSU LKM 格式。')
    # KernelSU v3.3.1 adds this flag for its bundled LKM. Do not accept arbitrary
    # feature flags or relax the allowlist for unrelated new ramdisk entries.
    if 'ksu_config' in new:
        require('ksu_config' not in old and new['ksu_config'][3] == b'bundled=1', 'ksu_config 含有尚未支持的设置；仅支持官方默认 bundled=1。')
        required.add('ksu_config')
    require(new['stock_image.sha1'][3].decode().strip() == hashlib.sha1(original).hexdigest(), '修补镜像对应的原厂 SHA-1 不一致；可能选择了旧文件。')
    require(new['init.real'] == old['init'], '修补镜像未完整保留原始 init。')
    for name in required:
        mode,uid,gid = new[name][:3]
        require(mode & 0o170000 == 0o100000 and uid == gid == 0 and mode & 0o400, f'{name} 不是 root 拥有的可读普通文件。')
        if name in ('init','init.real'):
            require(mode & 0o100, f'{name} 缺少执行权限。')
    require(arm64_elf(new['init'][3]) and arm64_elf(new['kernelsu.ko'][3]), 'KernelSU init 或内核模块不是 ARM64 ELF。')
    mm = re.match(r'(\d+\.\d+)\.',kernel)
    vermagic = re.search(rb'vermagic=([^\x00]+)',new['kernelsu.ko'][3])
    require(mm and vermagic and vermagic[1].startswith(mm[1].encode()+b'.'), 'KernelSU 模块的内核主次版本不匹配。')
    changed = {n for n in new if old.get(n) != new[n]}
    unexpected = sorted((changed-required) | (set(old)-set(new)))
    require(set(old).issubset(new) and changed == required, 'ramdisk 出现预期之外的修改：'+(', '.join(unexpected) or '必要文件未按预期改变'))
    return {'original_sha1':hashlib.sha1(original).hexdigest(), 'patched_sha256':hashlib.sha256(patched).hexdigest(), 'module_vermagic':vermagic[1].decode(errors='replace'), 'changed':sorted(changed)}
