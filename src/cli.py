"""Windows CLI: firmware -> verified stock -> manual patch -> active-slot flash."""
import argparse
import copy
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from firmware import ToolError, require, extract_ota, extract_fastboot, sha256
from images import header, ramdisk, verify_patch
from phone import Bridge, same_phone, flash_checked, wait_boot
from ksu_workflow import wait_for_patch, push_original, make_recovery_command
from terminal_ui import TerminalUI, WorkflowView, VERSION

class Logger:
    def __init__(self,path,display=print):
        self.path=path;self.display=display
    def __call__(self,message):
        self.display(message)
        with self.path.open('a',encoding='utf-8') as f:
            f.write(f'[{datetime.now().isoformat(timespec="seconds")}] {message}\n')

def save(path, data):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

class DeviceLock:
    def __init__(self,serial):
        self.handle=None
        if os.name=='nt':
            from ctypes import wintypes
            self.api=ctypes.WinDLL('kernel32',use_last_error=True)
            self.api.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
            self.api.CreateMutexW.restype=wintypes.HANDLE
            self.api.CloseHandle.argtypes=[wintypes.HANDLE]
            self.handle=self.api.CreateMutexW(None,False,'Local\\KernelSURootTool-'+serial.replace(':','_'))
            err=ctypes.get_last_error()
            require(self.handle, '无法创建设备操作锁。')
            if err==183:
                self.close()
                raise ToolError('另一个工具实例正在处理这台手机，请先关闭它。')
    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle);self.handle=None

def parser():
    p=argparse.ArgumentParser(description='KernelSU Root 工具：完整卡刷包/线刷包 -> init_boot -> 手动修补 -> 自动刷入当前槽位。',epilog='默认运行会在检测到本次新修补文件并校验通过后自动刷写；Ctrl+C 可在刷写前退出。')
    p.add_argument('source',nargs='?',help='卡刷包 HTTPS 链接/本地 ZIP，或线刷包 TGZ/TAR/ZIP/解压目录')
    p.add_argument('--type',choices=['ota','fastboot'],help='ota=卡刷包；fastboot=线刷包。不指定时显示选择菜单')
    p.add_argument('--tools',type=Path,help='包含 adb.exe 和 fastboot.exe 的文件夹')
    p.add_argument('--serial',help='指定手机 ADB 序列号')
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--check',action='store_true',help='只读取手机、检查包并提取到电脑，不传输、不重启、不刷写')
    modes.add_argument('--prepare-only',action='store_true',help='提取并传到手机后结束，不等待修补或刷写')
    p.add_argument('--output',type=Path,help='会话与备份保存目录，默认工具旁 sessions')
    p.add_argument('--timeout',type=int,default=1800,help='等待手动修补秒数，默认 1800')
    p.add_argument('--plain',action='store_true',help='禁用颜色和动态刷新，保留静态文字布局')
    p.add_argument('--menu',action='store_true',help='打开交互主菜单')
    p.add_argument('--version',action='version',version=VERSION)
    return p

def base_dir():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]

def tools_dir(args):
    tools=args.tools or base_dir()/'platform-tools'
    if not args.tools and not (tools/'adb.exe').is_file() and shutil.which('adb.exe'):
        tools=Path(shutil.which('adb.exe')).parent
    return tools

def menu_status(args):
    try:
        bridge=Bridge(tools_dir(args),args.serial)
        bridge.connect()
        return bridge.describe(),''
    except (ToolError,OSError) as exc:
        return None,str(exc)

def choose_type(ui):
    ui.message('选择固件类型\n[1] 完整卡刷包：本地 ZIP 或 HTTPS 链接\n[2] 线刷包：本地 TGZ / TAR / ZIP / 解压目录\n[0] 返回',style='bright_blue')
    while True:
        selected=ui.prompt('输入 1 / 2 / 0')
        if selected in ('0','1','2'):
            return {'0':None,'1':'ota','2':'fastboot'}[selected]
        ui.message('选项无效，请输入 1、2 或 0。')

def interactive_menu(args,ui):
    while True:
        try:
            status,error=menu_status(args)
            ui.menu(status,error)
            choice=ui.prompt('请输入选项')
            if choice=='0':return 0
            if choice in ('1','2','3'):
                options=copy.copy(args)
                options.menu=False
                options.type={'1':'ota','2':'fastboot'}.get(choice) or choose_type(ui)
                if not options.type:continue
                options.check=choice=='3' or args.check
                options.source=args.source or ui.prompt('粘贴固件链接或本地路径（0 返回）')
                if options.source=='0':continue
                execute_workflow(options,ui)
            elif choice=='4':
                ui.clear();ui.console.print(ui.banner(compact=True))
                status,error=menu_status(args)
                ui.console.print(ui.device_panel(status,error))
                ui.message('此页面仅检查连接和设备状态。连接正常不代表固件或修补镜像已经通过校验。','cyan')
            elif choice=='5':
                ui.backups(args.output or base_dir()/'sessions')
            elif choice=='6':
                ui.help()
            else:
                ui.message('选项无效，请输入 0 到 6。')
            ui.pause()
        except (KeyboardInterrupt,EOFError):
            ui.console.print('\n已退出主菜单。')
            return 0

def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8',errors='replace')
        sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    args=parser().parse_args(argv)
    ui=TerminalUI(plain=args.plain)
    if args.menu or not args.source and not args.type:
        return interactive_menu(args,ui)
    return execute_workflow(args,ui)

def execute_workflow(args,ui):
    session=None;log=print;lock=None;record={};view=None
    try:
        require(10 <= args.timeout <= 86400, '--timeout 必须介于 10 与 86400 秒。')
        if not args.type:
            args.type=choose_type(ui)
            if not args.type:return 0
        source=(args.source or ui.prompt('输入固件链接或本地路径')).strip().strip('"')
        require(source, '没有指定固件包。')
        if not source.lower().startswith(('http://','https://')):
            source=str(Path(source).expanduser().resolve())
            require(Path(source).exists(), '指定的固件路径不存在。')
        tools=tools_dir(args)
        bridge=Bridge(tools,args.serial)
        bridge.connect()
        lock=DeviceLock(bridge.serial)
        phone=bridge.snapshot()
        parent=(args.output or base_dir()/'sessions').resolve()
        parent.mkdir(parents=True,exist_ok=True)
        token=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
        session=parent/token;session.mkdir()
        mode='check' if args.check else 'prepare-only' if args.prepare_only else 'automatic'
        view=WorkflowView(ui,phone,mode,session)
        view.start();view.step('verify')
        log=Logger(session/'run.log',view.event);bridge.log=log
        record={'tool_version':VERSION,'source':source,'kind':args.type,'phone':phone,'status':'checking','mode':'check' if args.check else 'prepare-only' if args.prepare_only else 'automatic'}
        save(session/'session.json',record)
        log(f"设备：{phone['model']} / {phone['device']} / {phone['version']} / 当前槽位 {phone['slot'].upper()}")
        log(f'备份和日志：{session}')
        log('模式：只读提取检查。' if args.check else '模式：仅准备原厂镜像。' if args.prepare_only else '模式：检测到本次新修补文件、校验通过后，将自动重启并刷入当前 init_boot 槽位。')
        log('Ctrl+C 可退出；刷写进行时请保持连接。请提前备份重要数据。')
        data,firmware=(extract_ota if args.type=='ota' else extract_fastboot)(source,phone,log,on_verified=lambda:view.step('extract'))
        header(data)
        original_entries=ramdisk(data)
        require('init' in original_entries and 'kernelsu.ko' not in original_entries, '原厂镜像不完整或已经包含 KernelSU。')
        original=session/'init_boot.img';original.write_bytes(data)
        record['firmware']=firmware
        record['stock_sha256']=sha256(data)
        require(sha256(original.read_bytes())==record['stock_sha256'], '电脑备份写入校验失败。')
        record['status']='stock_verified'
        save(session/'session.json',record)
        save(session/'firmware-verification.json',firmware)
        log('原厂镜像已保存，SHA-256：'+record['stock_sha256'])
        if args.type=='fastboot':
            log('线刷包按 misc.txt 匹配版本；镜像已记录 SHA-256，但未验证厂商签名。请使用可信来源的完整包。')
        recovery='原厂恢复说明\n\n仅用于本次记录的同一手机、同一系统和槽位。\n将手机置于 Fastboot 后先核对 product 和 current-slot。不要把此命令用于更新后的系统。\n在 platform-tools 可用、且工作目录为本备份目录时执行：\n'+make_recovery_command(bridge.serial,phone['slot'])+'\n确认写入成功后执行 fastboot.exe -s '+bridge.serial+' reboot\n\n不要运行线刷包的 flash_all / flash_all_lock；本工具没有清除数据或重新上锁步骤。\n'
        (session/'恢复说明.txt').write_text(recovery,encoding='utf-8-sig')
        if args.check:
            log('检查完成：已提取到电脑，未向手机写入文件或分区。')
            view.finish('提取与校验完成。原厂镜像已保存在电脑，未向手机传输或刷写。')
            return 0
        view.step('push')
        require('package:me.weishu.kernelsu' in bridge.shell('pm list packages me.weishu.kernelsu'), '请先在手机安装官方 KernelSU 管理器，再重新运行。')
        baseline=bridge.patches()
        remote='/sdcard/Download/init_boot_'+token.replace('-','_')+'_stock.img'
        push_original(bridge,original,remote)
        record.update(baseline=baseline,remote_stock=remote,status='stock_uploaded')
        save(session/'session.json',record)
        log('\n原厂镜像已传到手机并校验：'+remote)
        if args.prepare_only:
            log('准备完成。若要自动刷入，请正常重跑工具并重新生成一个新修补文件。')
            view.finish('准备完成。镜像已传入手机 Download，本次不继续刷写。')
            return 0
        view.step('manual');view.manual(remote)
        log('\n现在请在手机上操作：\n1. 打开 KernelSU；确认设备受支持。如显示“不支持”，按 Ctrl+C 退出。\n2. 安装 -> 选择并修补一个文件。\n3. 选择 Download 中刚传入的 '+Path(remote).name+'。\n4. 修补成功后保持 USB 连接，工具将自动继续，无需按回车。\n不要选择“直接安装”或“安装到另一个槽位”。')
        record['status']='waiting_for_patch';save(session/'session.json',record)
        patched=wait_for_patch(bridge,baseline,len(data),session,timeout=args.timeout)
        record['status']='validating_patch';save(session/'session.json',record)
        verification=verify_patch(data,patched.read_bytes(),phone['kernel'])
        save(session/'patch-verification.json',verification)
        record.update(status='patch_verified',patch=verification)
        save(session/'session.json',record)
        log('检测到新修补文件；原厂 SHA-1、原始 init 和 KernelSU 模块结构校验通过。')
        same_phone(phone,bridge.snapshot())
        require(sha256(original.read_bytes())==record['stock_sha256'], '原厂备份发生变化，停止。')
        require(sha256(patched.read_bytes())==verification['patched_sha256'], '修补镜像发生变化，停止。')
        log('即将进入 Fastboot；再次核对机型、解锁状态、当前槽位与分区大小。')
        view.step('flash')
        record['status']='entering_fastboot';save(session/'session.json',record)
        bridge.adb('reboot','bootloader')
        bridge.wait_fastboot()
        require(sha256(patched.read_bytes())==verification['patched_sha256'], '进入 Fastboot 期间修补文件发生变化。')
        record['status']='flashing';save(session/'session.json',record)
        target,output=flash_checked(bridge,phone,patched)
        log(output)
        record.update(status='flashed_waiting_boot',target=target)
        save(session/'session.json',record)
        log('已刷写 '+target+' 并重启，正在等待系统启动和 KernelSU 加载。')
        view.step('boot')
        wait_boot(bridge)
        final=bridge.snapshot();same_phone(phone,final)
        view.phone=final
        record['status']='success';save(session/'session.json',record)
        log('成功：系统正常启动，KernelSU 模块为 Live。请打开管理器给需要 Root 的应用授权。')
        view.finish('系统正常启动，KernelSU 模块为 Live。请打开管理器给需要 Root 的应用授权。')
        return 0
    except KeyboardInterrupt:
        log('\n用户取消。若正在刷写或重启，请先观察手机状态，勿立即拔线。')
        if session:
            record.update(status='interrupted',previous_status=record.get('status'));save(session/'session.json',record)
        if view:view.fail('用户取消。若已经进入刷写或重启阶段，请观察手机状态并保留 USB 连接。')
        return 130
    except Exception as exc:
        log('\n已停止：'+str(exc))
        note='尚未开始刷写，手机分区未修改。'
        if session:
            (session/'error-details.txt').write_text(traceback.format_exc(),encoding='utf-8')
            record.update(status='failed',previous_status=record.get('status'),error=str(exc));save(session/'session.json',record)
            log('备份和错误记录：'+str(session))
            if record.get('previous_status') in ('flashing','flashed_waiting_boot') and (session/'init_boot.img').exists():
                note='如果手机无法启动，请参照本次备份目录的恢复说明。不要重复盲目刷写。'
                log(note)
            else:
                log('本次尚未开始刷写，手机分区未修改。')
        if view:view.fail(str(exc)+'\n\n'+note)
        else:ui.message(str(exc)+'\n'+note,style='red')
        return 1
    finally:
        if view:view.close()
        if lock:lock.close()

def console_entry(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        code = main(args)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code,int) else 1
    if (sys.stdin.isatty() and os.environ.get('KSU_FROM_CMD') != '1'
            and os.environ.get('KSU_NO_PAUSE') != '1'
            and (code != 0 or bool(args) and '--menu' not in args)
            and not any(arg in ('--help','-h','--version') for arg in args)):
        try:
            input('\n操作已结束，请查看上方结果。按回车关闭窗口……')
        except (EOFError,KeyboardInterrupt):
            pass
    return code

if __name__=='__main__':
    raise SystemExit(console_entry())
