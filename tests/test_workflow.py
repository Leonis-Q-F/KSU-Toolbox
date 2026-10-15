import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ksu_workflow import wait_for_patch, push_original, make_recovery_command
from firmware import ToolError

class Device:
    def __init__(self,states,data=b'good',digest=None):
        self.states=iter(states);self.last={};self.data=data
        self.digest=digest or hashlib.sha256(data).hexdigest();self.calls=[]
    def patches(self):
        self.last=next(self.states,self.last);return self.last
    def remote_hash(self,path):return self.digest
    def adb(self,*args,**kwargs):
        self.calls.append(args)
        if args[0]=='pull':Path(args[2]).write_bytes(self.data)
        return 'success'

class WorkflowTests(unittest.TestCase):
    def test_waits_until_new_file_is_stable_and_downloads_it(self):
        name='/sdcard/Download/kernelsu_patched_new.img'
        old={'/sdcard/Download/kernelsu_patched_old.img':(4,1)}
        dev=Device([old,dict(old,**{name:(1,2)}),dict(old,**{name:(4,3)}),dict(old,**{name:(4,3)})])
        with tempfile.TemporaryDirectory() as td:
            result=wait_for_patch(dev,old,4,Path(td),timeout=1,poll=0)
            self.assertEqual(result.read_bytes(),b'good')
            self.assertEqual(len([c for c in dev.calls if c[0]=='pull']),1)
    def test_partial_file_is_not_downloaded(self):
        dev=Device([{'/sdcard/Download/kernelsu_patched_new.img':(1,2)}])
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ToolError):wait_for_patch(dev,{},4,Path(td),timeout=.01,poll=0)
        self.assertEqual(dev.calls,[])
    def test_corrupted_pull_is_rejected(self):
        item={'/sdcard/Download/kernelsu_patched_new.img':(4,2)}
        dev=Device([item,item],digest='0'*64)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ToolError):wait_for_patch(dev,{},4,Path(td),timeout=1,poll=0)
    def test_push_must_pass_hash_check(self):
        dev=Device([],digest='0'*64)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'init_boot.img';p.write_bytes(b'good')
            with self.assertRaises(ToolError):push_original(dev,p,'/sdcard/Download/init_boot_test_stock.img')
    def test_recovery_command_targets_only_recorded_slot_and_original(self):
        line=make_recovery_command('ABC123','b')
        self.assertIn('flash init_boot_b',line)
        self.assertIn('init_boot.img',line)
        self.assertNotIn('patched',line)

if __name__=='__main__':unittest.main()
