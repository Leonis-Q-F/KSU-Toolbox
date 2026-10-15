"""Terminal presentation only; no device mutations or firmware decisions."""
import json
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

VERSION = '1.1.2'
BLUE = 'bright_blue'
MUTED = 'bright_black'
STEPS = [('verify','匹配固件'),('extract','提取镜像'),('push','传入手机'),('manual','手动修补'),('flash','刷入槽位'),('boot','开机验证')]
LOGO = '\n'.join([
    '██╗  ██╗███████╗██╗   ██╗',
    '██║ ██╔╝██╔════╝██║   ██║',
    '█████╔╝ ███████╗██║   ██║',
    '██╔═██╗ ╚════██║██║   ██║',
    '██║  ██╗███████║╚██████╔╝',
    '╚═╝  ╚═╝╚══════╝ ╚═════╝ ',
])

def text(value='', style=''):
    value=re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '?',str(value))
    return Text(value,style=style)

def field(label,value,style=''):
    result=text(label+'  ',MUTED)
    result.append_text(text(value,style))
    return result

class TerminalUI:
    def __init__(self, console=None, clear=True, plain=False):
        self.console=console or Console(highlight=False,markup=False,no_color=plain)
        self.clear_enabled=clear and not plain
        self.plain=plain

    def clear(self):
        if self.clear_enabled and self.console.is_terminal:
            self.console.clear()

    def banner(self, compact=False):
        if compact or self.console.width < 78 or self.console.height < 32:
            return text(f'KSU TOOLBOX  /  v{VERSION}','bold '+BLUE)
        grid=Table.grid(expand=True,padding=(0,3))
        grid.add_column(width=25,no_wrap=True)
        grid.add_column(ratio=1)
        subtitle=text('TOOLBOX\n','bold '+BLUE)
        subtitle.append(f'v{VERSION}  ·  Windows x64\n\n','cyan')
        subtitle.append('KernelSU 固件与 Root 助手\n')
        subtitle.append(datetime.now().strftime('%Y / %m / %d  %H:%M'),MUTED)
        grid.add_row(text(LOGO,BLUE),subtitle)
        return grid

    def device_panel(self, status=None, error='', compact=False):
        if not status:
            message=text('○ 等待连接手机\n','yellow')
            message.append_text(text(error or '请连接 USB、启用调试，并允许电脑授权。',MUTED))
            return Panel(message,title=text('设备状态'),border_style=MUTED,padding=(1,2))
        locked=status.get('locked')
        unlocked=locked=='0' and status.get('state')=='unlocked'
        bl='已解锁' if unlocked else '已锁定' if locked=='1' else '未知'
        slot=status.get('slot','').lstrip('_').upper() or '未知'
        device=(status.get('marketname') or status.get('model') or 'Android')+' · '+status.get('device','未知')
        if compact:
            lines=text(device+'    '+slot+' 槽位\n')
            lines.append_text(text(status.get('version') or '未知'))
            lines.append('\nBL '+bl+'  ·  KernelSU '+status.get('kernelsu','未读取'))
            return Panel(lines,title=text('设备状态'),border_style=BLUE,padding=(0,1))
        items=[field('设备',device),field('USB','已连接','green'),
               field('系统',status.get('version') or '未知'),field('当前槽位',slot,'cyan'),
               field('BL 锁',bl,'green' if unlocked else 'yellow'),field('KernelSU',status.get('kernelsu','未读取'),'green' if status.get('kernelsu')=='已加载' else 'yellow')]
        grid=Table.grid(expand=True,padding=(0,2))
        if self.console.width>=78:
            grid.add_column(ratio=3);grid.add_column(ratio=2)
            for i in range(0,len(items),2):grid.add_row(items[i],items[i+1])
        else:
            grid.add_column()
            for item in items:grid.add_row(item)
        return Panel(grid,title=text('设备状态'),border_style=BLUE,padding=(0 if self.console.height<30 else 1,2))

    def menu(self,status=None,error=''):
        self.clear()
        self.console.print(self.banner())
        self.console.print()
        self.console.print(self.device_panel(status,error))
        grid=Table.grid(expand=True,padding=(0,2))
        def action(number,label,description):
            title=text(f'[{number}]  ','bold '+BLUE)
            title.append(label,'bold')
            title.append('\n     '+description,MUTED)
            return title
        left=[action('1','从卡刷包开始','完整 OTA · 本地 ZIP / HTTPS'),action('2','从线刷包开始','TGZ / TAR / ZIP / 解压目录'),action('3','仅提取原厂镜像','核对当前版本，备份到电脑')]
        right=[action('4','检查设备连接','USB / 系统 / BL / 活动槽位'),action('5','查看备份与日志','按运行时间查看本地记录'),action('6','使用帮助与支持范围','操作流程、条件和故障处理')]
        if self.console.width>=78:
            grid.add_column(ratio=1);grid.add_column(ratio=1)
            grid.add_row(text('固件与 Root','bold cyan'),text('检查与记录','bold cyan'))
            for l,r in zip(left,right):
                grid.add_row(l,r)
                if self.console.height>=32:grid.add_row('','')
        else:
            grid.add_column()
            for item in left+right:grid.add_row(item)
        self.console.print(Panel(grid,border_style=MUTED,padding=(0 if self.console.height<30 else 1,2)))
        footer=text('[0] 退出','bold')
        footer.append('    完整固件 · 当前版本 · 原厂备份',MUTED)
        self.console.print(footer)
        self.console.print(text('支持小米 / 红米 / POCO 的 ARM64 A/B init_boot 设备。',MUTED))

    def prompt(self,message):
        self.console.print(text('\n'+message+' > ','bold cyan'),end='')
        return input().strip()

    def pause(self):
        self.prompt('按回车返回主菜单')

    def message(self,message,style='yellow'):
        self.console.print(Panel(text(message),border_style=style))

    def help(self):
        self.clear();self.console.print(self.banner(compact=True))
        self.console.print(Panel(text('① 连接手机，允许 USB 调试\n② 选择当前版本的完整卡刷包或线刷包\n③ 工具提取、校验并备份原厂 init_boot\n④ 用户在 KernelSU 选择并修补刚传入的文件\n⑤ 检测到新文件后，校验并自动刷入活动槽位\n⑥ 重启检查，在管理器给应用授权'),title=text('使用流程'),border_style=BLUE))
        self.console.print(Panel(text('需要 BL 已解锁、ARM64、A/B 槽位、v4 init_boot。\n仅支持官方 KernelSU 的已知 LKM 修补格式。\n增量 OTA、旧版本包、独立 IMG、Magisk/APatch 不在当前范围。\n使用前备份重要数据，刷写期间保持 USB 连接。\n哈希验证用于完整性检查，不等于厂商签名验证。'),title=text('支持范围'),border_style=MUTED))
        self.console.print(text('命令行：--type ota|fastboot  --check  --prepare-only\n其他参数：--tools  --serial  --output  --plain  --help',MUTED))

    def backups(self,parent):
        self.clear();self.console.print(self.banner(compact=True))
        table=Table(box=box.SIMPLE,border_style=MUTED,expand=True)
        table.add_column('运行记录',style='cyan',ratio=2)
        table.add_column('设备',ratio=2)
        table.add_column('结果',ratio=1)
        names={'success':'成功','failed':'失败','interrupted':'已取消','stock_verified':'已备份','stock_uploaded':'已传入','waiting_for_patch':'等待修补','validating_patch':'校验修补','flashing':'刷写中'}
        rows=sorted((p for p in Path(parent).glob('*/session.json') if p.is_file()),key=lambda p:p.parent.name,reverse=True)[:12]
        for path in rows:
            try:
                if path.stat().st_size>1024*1024:continue
                record=json.loads(path.read_text(encoding='utf-8'))
                phone=record.get('phone',{})
                table.add_row(text(path.parent.name),text(phone.get('device','未知')),text(names.get(record.get('status'),record.get('status','未知'))))
            except (OSError,ValueError,TypeError):
                table.add_row(text(path.parent.name),text('—'),text('无法读取','yellow'))
        self.console.print(Panel(table,title=text('最近的备份与日志'),border_style=BLUE))
        if not rows:self.console.print(text('暂无记录。完成提取后会自动保存原厂镜像和日志。',MUTED))
        self.console.print(field('保存目录',Path(parent).resolve()))

class WorkflowView:
    def __init__(self,ui,phone,mode,backup):
        self.ui=ui;self.phone=phone;self.mode=mode;self.backup=str(backup)
        self.states={key:'pending' for key,_ in STEPS}
        self.current=None;self.manual_file=None;self.events=deque(maxlen=3)
        self.result='';self.error=False;self.started=time.monotonic();self.live=None

    def start(self):
        self.ui.clear()
        if self.ui.console.is_terminal and not self.ui.plain and self.ui.console.height>=22 and self.ui.console.width>=50:
            self.live=Live(console=self.ui.console,get_render=self.render,refresh_per_second=3,redirect_stdout=False,redirect_stderr=False,vertical_overflow='visible')
            self.live.start(refresh=True)
        else:
            self.ui.console.print(self.ui.banner(compact=True))

    def refresh(self):
        if self.live:self.live.refresh()

    def step(self,key):
        if self.current and self.states[self.current]=='active':self.states[self.current]='done'
        self.current=key;self.states[key]='active'
        self.refresh()

    def manual(self,remote):
        self.manual_file=remote.rsplit('/',1)[-1];self.refresh()

    def event(self,message):
        self.events.append(str(message))
        if not self.live:self.ui.console.print(text(message))
        self.refresh()

    def finish(self,message):
        if self.current:self.states[self.current]='done'
        for key,state in self.states.items():
            if state=='pending':self.states[key]='skipped'
        self.result=message;self.manual_file=None;self.refresh()

    def fail(self,message):
        if self.current:self.states[self.current]='failed'
        self.result=message;self.error=True;self.manual_file=None;self.refresh()

    def close(self):
        if self.live:self.live.stop();self.live=None
        elif self.result:self.ui.console.print(self.render())

    def render(self):
        compact=self.ui.console.height<34
        modes={'automatic':'自动 Root 流程','check':'仅提取与检查','prepare-only':'准备原厂镜像'}
        grid=Table.grid(expand=True,padding=(0,2))
        grid.add_column(width=5);grid.add_column(ratio=1);grid.add_column(width=10)
        symbols={'done':('[OK]','green','已完成'),'active':('[>>]','yellow','进行中'),'pending':('[  ]',MUTED,'待执行'),'skipped':('[--]',MUTED,'未执行'),'failed':('[!!]','red','已停止')}
        for key,label in STEPS:
            mark,style,status=symbols[self.states[key]]
            grid.add_row(text(mark,style),text(label,'bold' if key==self.current else ''),text(status,style))
        done=sum(state=='done' for state in self.states.values())
        progress=text(f'步骤 {done} / {len(STEPS)}',MUTED)
        progress.append('    已运行 '+str(int(time.monotonic()-self.started))+' 秒',MUTED)
        stage_title=modes[self.mode]+(f' · {done}/6' if compact else '')
        blocks=[self.ui.banner(compact=True)]
        if not compact:blocks.append(text())
        blocks.append(self.ui.device_panel(self.phone,compact=compact))
        blocks.append(Panel(grid if compact else Group(grid,text(),progress),title=text(stage_title),border_style=BLUE,padding=(0 if compact else 1,1 if compact else 2)))
        if self.manual_file and self.current=='manual' and not self.result:
            instructions=text('KernelSU：选择并修补一个文件\n' if compact else '请在手机 KernelSU 中操作\n','bold yellow')
            if not compact:instructions.append('安装 → 选择并修补一个文件\n')
            instructions.append_text(text('Download / '+self.manual_file,'cyan'))
            instructions.append('\n勾选备份原厂镜像；完成后保持 USB 连接。' if compact else '\n勾选备份原厂镜像。完成后保持连接，工具将自动继续。')
            blocks.append(Panel(instructions,title=text('需要你手动完成'),border_style='yellow'))
        if self.result:
            blocks.append(Panel(text(self.result),title=text('已停止' if self.error else '操作完成'),border_style='red' if self.error else 'green'))
        elif self.events and not (self.manual_file and self.current=='manual'):
            latest=self.events[-1] if compact else '\n'.join(self.events)
            blocks.append(Panel(text(latest),title=text('当前信息'),border_style=MUTED))
        location=field('备份 / 日志',self.backup)
        if compact:location.no_wrap=True;location.overflow='ellipsis'
        blocks.append(location)
        return Group(*blocks)
