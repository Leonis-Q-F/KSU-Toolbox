import gzip
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from firmware import ToolError
from images import verify_patch
from test_end_to_end import images, image, elf

def modify(patched, mutation):
    size=struct.unpack_from('<I',patched,12)[0]
    cpio=bytearray(gzip.decompress(patched[4096:4096+size]))
    mutation(cpio)
    compressed=gzip.compress(bytes(cpio),mtime=0)
    out=bytearray(patched)
    out[4096:]=bytes(len(out)-4096)
    struct.pack_into('<I',out,12,len(compressed))
    out[4096:4096+len(compressed)]=compressed
    return bytes(out)

class RamdiskSafetyTests(unittest.TestCase):
    def test_second_cpio_archive_cannot_override_validated_init(self):
        original,patched=images()
        second=image({'init':elf(b'replacement')})
        size=struct.unpack_from('<I',second,12)[0]
        payload=gzip.decompress(second[4096:4096+size])
        bad=modify(patched,lambda buf:buf.extend(payload))
        with self.assertRaises(ToolError):verify_patch(original,bad,'6.6.118-android15')
    def test_init_must_have_execute_permission(self):
        original,patched=images()
        def change(buf):buf[14:22]=b'00008000'
        with self.assertRaises(ToolError):verify_patch(original,modify(patched,change),'6.6.118-android15')
    def test_hardlink_metadata_cannot_alias_boot_files(self):
        original,patched=images()
        def change(buf):buf[38:46]=b'00000002'
        with self.assertRaises(ToolError):verify_patch(original,modify(patched,change),'6.6.118-android15')
    def test_symlink_init_is_not_accepted_as_an_executable(self):
        original,patched=images()
        def change(buf):buf[14:22]=b'0000a1ff'
        with self.assertRaises(ToolError):verify_patch(original,modify(patched,change),'6.6.118-android15')
    def test_non_root_owned_init_rejected(self):
        original,patched=images()
        def change(buf):buf[22:30]=b'000007d0'
        with self.assertRaises(ToolError):verify_patch(original,modify(patched,change),'6.6.118-android15')

if __name__=='__main__':unittest.main()
