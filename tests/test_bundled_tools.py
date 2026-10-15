import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tools'))
from platform_tools import BUNDLE_FILES, verify_bundle
from release import source_files,source_archive
import cli

class BundledToolsTests(unittest.TestCase):
    def test_repo_contains_verified_complete_official_tool_set(self):
        metadata=verify_bundle(ROOT/'platform-tools')
        self.assertEqual(metadata['version'],'37.0.1')
        self.assertIn('adb.exe',metadata['files'])
        self.assertIn('fastboot.exe',metadata['files'])
        self.assertIn('NOTICE.txt',metadata['files'])
    def test_source_manifest_includes_tools_but_not_unknown_files(self):
        files={p.relative_to(ROOT).as_posix() for p in source_files(ROOT)}
        for name in BUNDLE_FILES:
            self.assertIn('platform-tools/'+name,files)
        self.assertNotIn('platform-tools/random.exe',files)
    def test_modified_bundled_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'platform-tools'
            shutil.copytree(ROOT/'platform-tools',target)
            (target/'adb.exe').write_bytes(b'not-the-official-executable')
            with self.assertRaises(ValueError):verify_bundle(target)
    def test_default_lookup_works_with_empty_path(self):
        with patch.object(cli,'base_dir',return_value=ROOT),patch.dict(os.environ,{'PATH':''}):
            self.assertEqual(cli.tools_dir(argparse.Namespace(tools=None)),ROOT/'platform-tools')
    @unittest.skipUnless(os.name=='nt','Windows executables')
    def test_bundled_commands_run_without_user_adb_installation(self):
        metadata=verify_bundle(ROOT/'platform-tools')
        for command in ('adb.exe','fastboot.exe'):
            result=subprocess.run([str(ROOT/'platform-tools'/command),'version' if command=='adb.exe' else '--version'],capture_output=True,text=True,timeout=15,env=dict(os.environ,PATH=''))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('37.0.1',result.stdout)

if __name__=='__main__':unittest.main()
