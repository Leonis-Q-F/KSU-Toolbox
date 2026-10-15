import hashlib
import io
import json
import os
import struct
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from firmware import match_ota, match_fastboot, extract_fastboot, extract_ota, ToolError
from images import verify_patch
from phone import Phone, flash_checked, select_new_patch

PHONE = {'device':'dada', 'version':'OS4.0.0.19.XOCCNXM',
         'internal':'17OS4.0.260920.220050279.QCPECN.S',
         'system_internal':'17OS4.0.260920.220050279.QCPECN.S',
         'security_patch':'2026-09-01', 'sdk':'37', 'kernel':'6.6.118-android15-8-test'}
META = {'pre-device':'dada', 'post-build-incremental':PHONE['internal'],
        'post-security-patch-level':'2026-09-01', 'post-sdk-level':'37'}

def pb(tag, value):
    def vint(n):
        out=bytearray()
        while n>127: out.append((n&127)|128); n>>=7
        return bytes(out)+bytes([n])
    if isinstance(value,int): return vint(tag<<3)+vint(value)
    return vint((tag<<3)|2)+vint(len(value))+value

def ota_fixture(path, corrupt=False, delta=False):
    image=b'X'*4096
    extent=pb(1,0)+pb(2,1)
    op=pb(1,0)+pb(2,0)+pb(3,4096)+pb(6,extent)+pb(8,hashlib.sha256(image).digest())
    info=pb(1,4096)+pb(2,hashlib.sha256(image).digest())
    partition=pb(1,b'init_boot')+pb(7,info)+pb(8,op)
    manifest=pb(3,4096)+pb(12,int(delta))+pb(13,partition)
    payload=struct.pack('>4sQQI',b'CrAU',2,len(manifest),0)+manifest+((b'Z'+image[1:]) if corrupt else image)
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('META-INF/com/android/metadata','\n'.join(f'{k}={v}' for k,v in META.items()))
        z.writestr('payload.bin',payload)
    return image

class MetadataTests(unittest.TestCase):
    def test_internal_build_matches_phone_even_when_marketing_version_differs(self):
        match_ota(META,PHONE,'dada-ota_full-OS4.0.0.19.XOCCNXM.zip')
    def test_wrong_device_is_rejected(self):
        with self.assertRaises(ToolError): match_ota(dict(META,**{'pre-device':'haotian'}),PHONE,'ota.zip')
    def test_wrong_internal_version_is_rejected(self):
        with self.assertRaises(ToolError): match_ota(dict(META,**{'post-build-incremental':'old'}),PHONE,'ota.zip')
    def test_misleading_filename_is_rejected(self):
        with self.assertRaises(ToolError): match_ota(META,PHONE,'dada-ota_full-OS3.0.307.0.WOCCNXM.zip')
    def test_wrong_patch_level_is_rejected(self):
        with self.assertRaises(ToolError): match_ota(dict(META,**{'post-security-patch-level':'2026-08-01'}),PHONE,'ota.zip')
    def test_missing_build_metadata_is_rejected(self):
        with self.assertRaises(ToolError): match_ota({'pre-device':'dada'},PHONE,'ota.zip')
    def test_fastboot_previous_system_rejected(self):
        with self.assertRaises(ToolError): match_fastboot({'device':'dada','build_number':'OS3.0.307.0.WOCCNXM'},PHONE)
    def test_fastboot_current_system_accepted(self):
        match_fastboot({'device':'dada','build_number':PHONE['version']},PHONE)

class ArchiveTests(unittest.TestCase):
    def test_ota_reconstructs_exact_image(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ota.zip'; expected=ota_fixture(path)
            data,report=extract_ota(str(path),PHONE)
            self.assertEqual(data,expected)
            self.assertEqual(report['sha256'],hashlib.sha256(expected).hexdigest())
    def test_corrupted_operation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ota.zip';ota_fixture(path,corrupt=True)
            with self.assertRaises(ToolError):extract_ota(str(path),PHONE)
    def test_incremental_payload_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ota.zip';ota_fixture(path,delta=True)
            with self.assertRaises(ToolError):extract_ota(str(path),PHONE)
    def test_tgz_reads_only_matching_package_without_extracting_paths(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'firmware.tgz'
            with tarfile.open(path,'w:gz') as t:
                for name,data in [('rom/misc.txt',f'device=dada\nbuild_number={PHONE["version"]}'.encode()),('rom/images/init_boot.img',b'IMAGE'),('../../escape',b'BAD')]:
                    entry=tarfile.TarInfo(name);entry.size=len(data);t.addfile(entry,io.BytesIO(data))
            data,report=extract_fastboot(str(path),PHONE)
            self.assertEqual(data,b'IMAGE')
            self.assertFalse((Path(td).parent/'escape').exists())
    def test_duplicate_fastboot_images_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'rom.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('misc.txt',f'device=dada\nbuild_number={PHONE["version"]}')
                z.writestr('images/init_boot.img',b'A'); z.writestr('other/images/init_boot.img',b'B')
            with self.assertRaises(ToolError):extract_fastboot(str(path),PHONE)

class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock=os.environ.get('KSU_TEST_STOCK_IMAGE')
        cls.patched=os.environ.get('KSU_TEST_PATCH_IMAGE')
    def test_real_kernel_su_patch_matches_original(self):
        if not self.stock or not self.patched:self.skipTest('Optional real-device fixtures not configured')
        verify_patch(Path(self.stock).read_bytes(),Path(self.patched).read_bytes(),PHONE['kernel'])
    def test_unmodified_image_is_not_a_patch(self):
        with self.assertRaises(ToolError):verify_patch(b'X'*8192,b'X'*8192,PHONE['kernel'])
    def test_truncated_image_rejected(self):
        with self.assertRaises(ToolError):verify_patch(b'ANDROID!'+bytes(100),b'ANDROID!'+bytes(90),PHONE['kernel'])
    def test_old_patch_is_never_auto_selected(self):
        baseline={'/sdcard/Download/kernelsu_patched_old.img':(8388608,100)}
        self.assertIsNone(select_new_patch(baseline,baseline))
    def test_multiple_new_patches_are_ambiguous(self):
        with self.assertRaises(ToolError):select_new_patch({}, {'/sdcard/Download/kernelsu_patched_a.img':(1,2),'/sdcard/Download/kernelsu_patched_b.img':(1,3)})
    def test_new_patch_selected(self):
        self.assertEqual(select_new_patch({}, {'/sdcard/Download/kernelsu_patched_new.img':(8388608,100)}),'/sdcard/Download/kernelsu_patched_new.img')

class FakeBridge:
    def __init__(self,slot='b',product='dada',unlocked='yes',fail=False):
        self.slot=slot;self.product=product;self.unlocked=unlocked;self.fail=fail;self.commands=[]
    def fastboot(self,*args,**kwargs):
        self.commands.append(args)
        if args[0]=='getvar':
            values={'product':self.product,'current-slot':self.slot,'unlocked':self.unlocked,'partition-size:init_boot_b':'0x800000','partition-size:init_boot_a':'0x800000'}
            return f'{args[1]}: {values[args[1]]}\nFinished. Total time: 0.001s'
        if args[0]=='flash':
            if self.fail:raise ToolError('write failed')
            return "Sending 'init_boot_b' OKAY\nWriting 'init_boot_b' OKAY\nFinished."
        return 'Rebooting OKAY'

class FlashTests(unittest.TestCase):
    def perform(self,bridge,slot='b'):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'patch.img';path.write_bytes(bytes(8388608))
            return flash_checked(bridge,{'device':'dada','slot':slot},path)
    def test_queries_active_slot_and_flashes_only_that_partition(self):
        bridge=FakeBridge();self.perform(bridge)
        flash=[x for x in bridge.commands if x[0]=='flash']
        self.assertEqual(len(flash),1);self.assertEqual(flash[0][1],'init_boot_b')
        self.assertEqual(bridge.commands[-1],('reboot',))
    def test_a_slot_is_supported(self):
        bridge=FakeBridge(slot='a');self.perform(bridge,'a')
        self.assertEqual([x[1] for x in bridge.commands if x[0]=='flash'],['init_boot_a'])
    def test_changed_slot_aborts_without_flash(self):
        bridge=FakeBridge(slot='a')
        with self.assertRaises(ToolError):self.perform(bridge)
        self.assertFalse(any(x[0]=='flash' for x in bridge.commands))
    def test_wrong_phone_aborts_without_flash(self):
        bridge=FakeBridge(product='haotian')
        with self.assertRaises(ToolError):self.perform(bridge)
        self.assertFalse(any(x[0]=='flash' for x in bridge.commands))
    def test_locked_bootloader_aborts(self):
        bridge=FakeBridge(unlocked='no')
        with self.assertRaises(ToolError):self.perform(bridge)
        self.assertFalse(any(x[0]=='flash' for x in bridge.commands))
    def test_failed_flash_does_not_reboot(self):
        bridge=FakeBridge(fail=True)
        with self.assertRaises(ToolError):self.perform(bridge)
        self.assertFalse(any(x[0]=='reboot' for x in bridge.commands))

if __name__=='__main__':unittest.main()
