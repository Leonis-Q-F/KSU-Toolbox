import time
from pathlib import Path

from firmware import ToolError, require, sha256
from phone import select_new_patch

def push_original(bridge, original, remote):
    bridge.adb('push',str(original),remote,timeout=90)
    require(bridge.remote_hash(remote) == sha256(Path(original).read_bytes()), '原厂镜像传输后哈希不一致。')

def wait_for_patch(bridge, baseline, expected_size, session, timeout=1800, poll=3):
    until = time.monotonic()+timeout
    previous = None
    while time.monotonic() < until:
        current = bridge.patches()
        selected = select_new_patch(baseline,current)
        if selected:
            size, modified = current[selected]
            state = (selected,size,modified)
            if size == expected_size and state == previous:
                before = bridge.remote_hash(selected)
                local = Path(session)/'kernelsu_patched.img'
                bridge.adb('pull',selected,str(local),timeout=90)
                after = bridge.remote_hash(selected)
                require(before == after == sha256(local.read_bytes()) and local.stat().st_size == expected_size, '修补文件传输失败或仍在写入，请重新运行并修补。')
                return local
            previous = state
        time.sleep(poll)
    raise ToolError('等待修补超时。原厂镜像和日志已保留；重新运行后请生成一个新的修补文件。')

def make_recovery_command(serial, slot):
    require(slot in ('a','b'), '无法确定恢复槽位。')
    return f'fastboot.exe -s {serial} flash init_boot_{slot} "init_boot.img"'
