import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from images import ramdisk, verify_patch
from firmware import ToolError
from test_end_to_end import images, image
import cli

class V331Tests(unittest.TestCase):
    def patched(self,config):
        original,previous=images()
        entries={n:e[3] for n,e in ramdisk(previous).items()}
        entries['ksu_config']=config
        return original,image(entries)
    def test_official_bundled_config_is_supported(self):
        original,patched=self.patched(b'bundled=1')
        self.assertIn('ksu_config',verify_patch(original,patched,'6.6.118-android15')['changed'])
    def test_unknown_config_is_rejected(self):
        original,patched=self.patched(b'bundled=1\nunknown=1')
        with self.assertRaises(ToolError):verify_patch(original,patched,'6.6.118-android15')
    def test_unrelated_new_file_still_rejected(self):
        original,patched=self.patched(b'bundled=1')
        entries={n:e[3] for n,e in ramdisk(patched).items()};entries['unknown-file']=b'bad'
        with self.assertRaises(ToolError):verify_patch(original,image(entries),'6.6.118-android15')
    def test_real_failed_session_now_validates(self):
        stock=os.environ.get('KSU_TEST_STOCK_IMAGE')
        patched=os.environ.get('KSU_TEST_V331_PATCH_IMAGE')
        if not stock or not patched:self.skipTest('Optional real-device fixture not configured')
        result=verify_patch(Path(stock).read_bytes(),Path(patched).read_bytes(),'6.6.118-android15')
        self.assertIn('ksu_config',result['changed'])
    def test_exe_error_holds_window(self):
        with patch.object(cli,'main',return_value=1),patch('sys.stdin.isatty',return_value=True),patch.dict('os.environ',{},clear=True),patch('builtins.input') as prompt:
            self.assertEqual(cli.console_entry([]),1)
            prompt.assert_called_once()
    def test_cmd_owns_its_pause_without_double_prompt(self):
        with patch.object(cli,'main',return_value=1),patch('sys.stdin.isatty',return_value=True),patch.dict('os.environ',{'KSU_FROM_CMD':'1'},clear=True),patch('builtins.input') as prompt:
            self.assertEqual(cli.console_entry([]),1)
            prompt.assert_not_called()

if __name__=='__main__':unittest.main()
