"""Run the actual CLI flow against simulated USB transport, never real flash."""
import gzip
import hashlib
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import cli
from test_tool import PHONE, META, pb

def elf(body):
    data=bytearray(64);data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',data,18,183)
    return bytes(data)+body

def image(entries):
    data=bytearray()
    for name,body in list(entries.items())+[('TRAILER!!!',b'')]:
        values=[1,0o100750,0,0,1,0,len(body),0,0,0,0,len(name.encode())+1,0]
        data.extend(b'070701'+''.join(f'{v:08x}' for v in values).encode()+name.encode()+b'\0')
        data.extend(bytes((-len(data))%4));data.extend(body);data.extend(bytes((-len(data))%4))
    compressed=gzip.compress(bytes(data),mtime=0)
    result=bytearray(16384);result[:8]=b'ANDROID!'
    struct.pack_into('<4I',result,8,0,len(compressed),0,1584);struct.pack_into('<I',result,40,4)
    result[4096:4096+len(compressed)]=compressed
    return bytes(result)

def images():
    init=elf(b'original-init')
    original=image({'init':init,'prop.default':b'ro.secure=1\n'})
    patched=image({'init':elf(b'ksuinit'),'prop.default':b'ro.secure=1\n','init.real':init,'kernelsu.ko':elf(b'vermagic=6.6.118-android15 SMP\0'),'stock_image.sha1':hashlib.sha1(original).hexdigest().encode()})
    return original,patched

def write_ota(path,original):
    extent=pb(1,0)+pb(2,len(original)//4096)
    op=pb(1,0)+pb(2,0)+pb(3,len(original))+pb(6,extent)+pb(8,hashlib.sha256(original).digest())
    partition=pb(1,b'init_boot')+pb(7,pb(1,len(original))+pb(2,hashlib.sha256(original).digest()))+pb(8,op)
    manifest=pb(3,4096)+pb(13,partition)
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('META-INF/com/android/metadata','\n'.join(f'{k}={v}' for k,v in META.items()))
        z.writestr('payload.bin',struct.pack('>4sQQI',b'CrAU',2,len(manifest),0)+manifest+original)

class USB:
    def __init__(self,original,patched):
        self.original=original;self.patched=patched;self.serial='TEST123';self.calls=[];self.num_lists=0;self.log=print
    def connect(self):return self.serial
    def snapshot(self):return dict(PHONE,serial=self.serial,model='test',slot='b')
    def patches(self):
        self.num_lists+=1
        return {} if self.num_lists==1 else {'/sdcard/Download/kernelsu_patched_test.img':(len(self.patched),1)}
    def remote_hash(self,path):return hashlib.sha256(self.patched if 'patched' in path else self.original).hexdigest()
    def adb(self,*args,**kwargs):
        self.calls.append(('adb',*args))
        if args[0]=='pull':Path(args[2]).write_bytes(self.patched)
        return 'OK'
    def shell(self,command,**kwargs):
        if command.startswith('pm list'):return 'package:me.weishu.kernelsu'
        if command=='getprop sys.boot_completed':return '1'
        if command=='cat /proc/modules':return 'kernelsu 163840 0 - Live 0x0 (O)'
        raise AssertionError(command)
    def wait_fastboot(self):self.calls.append(('wait_fastboot',))
    def fastboot(self,*args,**kwargs):
        self.calls.append(('fastboot',*args))
        if args[0]=='getvar':
            values={'product':'dada','current-slot':'b','unlocked':'yes','partition-size:init_boot_b':'0x4000'}
            return f'{args[1]}: {values[args[1]]}\nFinished.'
        if args[0]=='flash':return "Sending 'init_boot_b' OKAY\nWriting 'init_boot_b' OKAY"
        return 'Rebooting OKAY'

class EndToEndTests(unittest.TestCase):
    def test_success_view_uses_fresh_kernel_su_status(self):
        snapshots=[]
        original_snapshot=USB.snapshot
        def changing(usb):
            result=original_snapshot(usb)
            result['kernelsu']='未加载' if not snapshots else '已加载'
            snapshots.append(result)
            return result
        views=[]
        original_view=cli.WorkflowView
        def make_view(*args,**kwargs):
            view=original_view(*args,**kwargs);views.append(view);return view
        with patch.object(USB,'snapshot',changing),patch.object(cli,'WorkflowView',side_effect=make_view):
            code,calls,state=self.run_flow('ota')
        self.assertEqual(code,0)
        self.assertEqual(views[0].phone['kernelsu'],'已加载')
    def run_flow(self,kind,mode=None,corrupt=False):
        original,patched=images()
        if corrupt:patched=original
        usb=USB(original,patched)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            if kind=='ota':
                source=root/'ota.zip';write_ota(source,original)
            else:
                source=root/'rom';(source/'images').mkdir(parents=True)
                (source/'misc.txt').write_text('device=dada\nbuild_number='+PHONE['version'])
                (source/'images/init_boot.img').write_bytes(original)
            argv=['--type',kind,'--output',str(root/'sessions'),str(source)]
            if mode:argv.append(mode)
            with patch.object(cli,'Bridge',return_value=usb),patch('ksu_workflow.time.sleep'):
                code=cli.main(argv)
            session=next((root/'sessions').iterdir())
            self.assertEqual((session/'init_boot.img').read_bytes(),original)
            return code,usb.calls,(session/'session.json').read_text(encoding='utf-8')
    def test_ota_automatic_workflow_flashes_once_and_verifies_boot(self):
        code,calls,state=self.run_flow('ota')
        self.assertEqual(code,0)
        self.assertEqual(len([c for c in calls if c[:2]==('fastboot','flash')]),1)
        self.assertIn('"status": "success"',state)
    def test_fastboot_folder_uses_same_automatic_flow(self):
        code,calls,state=self.run_flow('fastboot')
        self.assertEqual(code,0);self.assertIn('"target": "init_boot_b"',state)
    def test_check_mode_has_no_device_write_calls(self):
        code,calls,state=self.run_flow('ota','--check')
        self.assertEqual(code,0);self.assertEqual(calls,[])
    def test_prepare_only_pushes_but_does_not_reboot_or_flash(self):
        code,calls,state=self.run_flow('ota','--prepare-only')
        self.assertEqual(code,0);self.assertEqual([c[:2] for c in calls],[('adb','push')])
    def test_bad_patch_never_enters_bootloader(self):
        code,calls,state=self.run_flow('ota',corrupt=True)
        self.assertEqual(code,1)
        self.assertFalse(any(c[:2] in [('adb','reboot'),('fastboot','flash')] for c in calls))

if __name__=='__main__':unittest.main()
