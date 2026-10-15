"""ADB/Fastboot transport and fail-closed flashing boundaries."""
import hashlib
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from firmware import ToolError, require

class Bridge:
    def __init__(self, tools, serial=None, log=print):
        self.tools = Path(tools)
        self.serial = serial
        self.log = log
        for name in ('adb.exe','fastboot.exe'):
            require((self.tools/name).is_file(), f'找不到 {name}，请通过 --tools 指定 platform-tools 文件夹。')

    def run(self, name, args, timeout=40):
        command = [str(self.tools/name), *args]
        try:
            result = subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f'{name} 超时。请检查 USB 连接和驱动；未自动重试刷写。') from exc
        except OSError as exc:
            raise ToolError(f'无法启动 {name}：{exc}') from exc
        text = result.stdout.strip()
        require(result.returncode == 0, f'{name} 失败（{result.returncode}）：\n{text}')
        return text

    def adb(self, *args, timeout=40):
        return self.run('adb.exe',(['-s',self.serial] if self.serial else [])+list(args),timeout)

    def fastboot(self, *args, timeout=40):
        require(self.serial, '没有锁定设备序列号。')
        return self.run('fastboot.exe',['-s',self.serial,*args],timeout)

    def connect(self):
        rows = self.run('adb.exe',['devices'],20).splitlines()
        rows = [line.split() for line in rows if re.match(r'^\S+\s+(device|unauthorized|offline)\b',line)]
        if self.serial:
            rows = [r for r in rows if r[0] == self.serial]
        require(len(rows) == 1, '请只连接一台手机，或使用 --serial 指定设备。')
        require(rows[0][1] == 'device', '手机尚未授权 USB 调试或处于离线状态。请解锁屏幕并允许调试。')
        self.serial = rows[0][0]
        require(re.fullmatch(r'[A-Za-z0-9._:-]+',self.serial), '设备序列号包含不支持的字符。')
        return self.serial

    def shell(self, command, timeout=40):
        return self.adb('shell',command,timeout=timeout)

    def describe(self):
        raw = self.adb('shell','getprop')
        props = dict(re.findall(r'^\[([^\]]+)\]: \[(.*)\]$',raw,re.M))
        keys = {'device':'ro.product.device','version':'ro.build.version.incremental','internal':'ro.bootimage.build.version.incremental','system_internal':'ro.system.build.version.incremental','security_patch':'ro.build.version.security_patch','sdk':'ro.build.version.sdk','model':'ro.product.model','marketname':'ro.product.marketname','slot':'ro.boot.slot_suffix','locked':'ro.boot.flash.locked','state':'ro.boot.vbmeta.device_state','completed':'sys.boot_completed','brand':'ro.product.brand'}
        result = {key:props.get(prop,'') for key,prop in keys.items()}
        result['slot'] = result['slot'].lstrip('_')
        result['kernel'] = self.adb('shell','uname -r').strip()
        result['serial'] = self.serial
        try:
            modules=self.shell('cat /proc/modules',timeout=10)
            result['kernelsu']='已加载' if re.search(r'^kernelsu\s.*\bLive\b',modules,re.M) else '未加载'
        except ToolError:
            result['kernelsu']='无法读取'
        return result

    def snapshot(self):
        result=self.describe()
        require(result['completed'] == '1', '手机尚未完成启动。')
        require(result['locked'] == '0' and result['state'] == 'unlocked', '必须先解锁 Bootloader。')
        require(result['slot'] in ('a','b'), '仅支持具有明确 A/B 活动槽位的设备。')
        require(result['brand'].lower() in ('xiaomi','redmi','poco'), '当前工具只支持小米/红米/POCO 设备。')
        require(result['version'] and result['device'], '无法读取手机机型或系统版本。')
        require(self.shell('test -e /dev/block/by-name/init_boot_'+result['slot']+' && echo exists') == 'exists', '设备没有对应的 init_boot 分区。')
        return result

    def patches(self):
        command = "for f in /sdcard/Download/kernelsu_patched*.img; do [ -f \"$f\" ] && stat -c '%s|%Y|%n' \"$f\"; done; true"
        text = self.shell(command)
        entries = {}
        for line in text.splitlines():
            parts = line.split('|',2)
            require(len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit(), '修补文件列表格式无法识别。')
            name = parts[2]
            require(re.fullmatch(r'/sdcard/Download/kernelsu_patched[A-Za-z0-9_.-]*\.img',name), '修补文件名称包含不支持的字符。')
            entries[name] = (int(parts[0]),int(parts[1]))
        return entries

    def remote_hash(self, path):
        text = self.shell('sha256sum '+shlex.quote(path))
        digest = text.split()[0] if text else ''
        require(re.fullmatch('[a-fA-F0-9]{64}',digest), '手机文件哈希读取失败。')
        return digest.lower()

    def wait_fastboot(self, seconds=90):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            text = self.run('fastboot.exe',['devices'],10)
            if any(line.split()[:1] == [self.serial] for line in text.splitlines()): return
            time.sleep(2)
        raise ToolError('未检测到同一台手机的 Fastboot。请检查驱动；镜像尚未刷写。')

@dataclass
class Phone:
    """Public holder for callers using the library."""
    data: dict

def select_new_patch(baseline, current):
    # Existing paths are never auto-selected, even if timestamps change.
    new = [name for name in current if name not in baseline]
    require(len(new) <= 1, '检测到多个新修补文件。请保留本次唯一结果后重试。')
    return new[0] if new else None

def same_phone(before, after):
    for key in ('serial','device','version','internal','system_internal','security_patch','kernel','slot'):
        require(before.get(key) == after.get(key), f'等待期间手机的 {key} 发生变化，停止刷写。')

def getvar(bridge, name):
    text = bridge.fastboot('getvar',name)
    match = re.search(r'^(?:\(bootloader\)\s*)?'+re.escape(name)+r':\s*(\S+)\s*$',text,re.M)
    require(match, f'无法可靠读取 Fastboot {name}。')
    return match[1]

def flash_checked(bridge, phone, patched):
    require(getvar(bridge,'product') == phone['device'], 'Fastboot 机型与原手机不一致。')
    slot = getvar(bridge,'current-slot')
    require(slot in ('a','b') and slot == phone['slot'], '进入 Fastboot 后槽位变化，停止刷写。')
    require(getvar(bridge,'unlocked').lower() in ('yes','true','1'), 'Fastboot 显示 BL 未解锁。')
    target = 'init_boot_'+slot
    size = int(getvar(bridge,'partition-size:'+target),16)
    require(size == Path(patched).stat().st_size, '修补镜像大小与目标分区不一致。')
    output = bridge.fastboot('flash',target,str(Path(patched).resolve()),timeout=120)
    require('FAILED' not in output and re.search(r'Writing.*OKAY',output,re.S), 'Fastboot 未明确报告写入成功，保留现场。')
    bridge.fastboot('reboot')
    return target, output

def wait_boot(bridge, seconds=180):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        try:
            if bridge.shell('getprop sys.boot_completed',timeout=10).strip() == '1':
                modules = bridge.shell('cat /proc/modules',timeout=10)
                require(re.search(r'^kernelsu\s.*\bLive\b',modules,re.M), '手机正常开机，但未检测到 Live 状态的 KernelSU。请查看管理器；不要重复自动刷写。')
                return True
        except ToolError as exc:
            if '手机正常开机' in str(exc): raise
        time.sleep(3)
    raise ToolError('尚未验证系统启动完成。请观察手机并检查 USB；必要时使用已保存的原厂镜像恢复。')
