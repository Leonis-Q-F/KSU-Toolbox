import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from release import source_files, source_archive

class ReleaseTests(unittest.TestCase):
    def test_source_package_excludes_user_backups_logs_and_unlisted_binaries(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in ('README.md','LICENSE','src/cli.py','tests/test_case.py','tools/build.py','.github/workflows/ci.yml','sessions/private/session.json','sessions/private/init_boot.img','platform-tools/unknown.exe','.env','src/private.img','build/debug.log','tests/__pycache__/cached.py'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('example')
            files=[p.relative_to(root).as_posix() for p in source_files(root)]
            self.assertIn('src/cli.py',files)
            self.assertIn('.github/workflows/ci.yml',files)
            self.assertFalse(any('sessions/' in p or 'platform-tools/' in p or '__pycache__' in p or p.endswith(('.img','.exe','.env','.log')) for p in files))
    def test_source_zip_has_one_root_and_matches_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'project';root.mkdir()
            (root/'README.md').write_text('hello')
            (root/'LICENSE').write_text('MIT')
            archive=Path(td)/'source.zip'
            source_archive(root,archive)
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(sorted(z.namelist()),['KSU-Toolbox/LICENSE','KSU-Toolbox/README.md'])

if __name__=='__main__':unittest.main()
