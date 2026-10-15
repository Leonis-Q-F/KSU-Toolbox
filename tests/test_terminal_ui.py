import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from terminal_ui import TerminalUI, WorkflowView
from rich.console import Console
from rich.cells import cell_len
import cli

STATUS={'device':'dada','model':'Xiaomi 15','version':'OS4.0.0.19.XOCCNXM','slot':'b','locked':'0','state':'unlocked','kernelsu':'已加载'}

class TerminalTests(unittest.TestCase):
    def ui(self,width=100,height=40):
        stream=io.StringIO()
        return TerminalUI(Console(file=stream,width=width,height=height,color_system=None),clear=False),stream
    def test_menu_contains_device_state_and_all_six_actions(self):
        ui,stream=self.ui()
        ui.menu(STATUS)
        text=stream.getvalue()
        for expected in ('TOOLBOX','Xiaomi 15','OS4.0.0.19.XOCCNXM','已解锁','已加载','卡刷包','线刷包','仅提取','设备连接','备份与日志','使用帮助','退出'):
            self.assertIn(expected,text)
    def test_chinese_menu_fits_narrow_terminal(self):
        ui,stream=self.ui(60)
        ui.menu(STATUS)
        self.assertTrue(all(cell_len(line)<=60 for line in stream.getvalue().splitlines()))
        self.assertIn('线刷包',stream.getvalue())
    def test_disconnected_state_still_shows_menu(self):
        ui,stream=self.ui()
        ui.menu(None,'未连接手机，请启用 USB 调试')
        self.assertIn('未连接手机',stream.getvalue())
        self.assertIn('卡刷包',stream.getvalue())
    def test_untrusted_device_text_is_rendered_literally(self):
        ui,stream=self.ui()
        ui.menu(dict(STATUS,model='[red]phone[/red]'))
        self.assertIn('[red]phone[/red]',stream.getvalue())
    def test_workflow_marks_current_step_and_keeps_patch_instructions(self):
        ui,stream=self.ui()
        view=WorkflowView(ui,STATUS,'automatic','C:/backups/session')
        for step in ('verify','extract','push','manual'):view.step(step)
        view.manual('/sdcard/Download/init_boot_current_stock.img')
        ui.console.print(view.render())
        text=stream.getvalue()
        self.assertIn('init_boot_current_stock.img',text)
        self.assertIn('选择并修补',text)
        self.assertEqual(view.states['push'],'done')
        self.assertEqual(view.states['manual'],'active')
        self.assertEqual(view.states['flash'],'pending')
    def test_check_result_does_not_claim_root_success(self):
        ui,stream=self.ui()
        view=WorkflowView(ui,STATUS,'check','C:/backups/session')
        view.step('verify');view.step('extract');view.finish('检查完成')
        self.assertEqual(view.states['push'],'skipped')
        self.assertEqual(view.states['flash'],'skipped')
        ui.console.print(view.render())
        self.assertNotIn('Root 成功',stream.getvalue())
    def test_failure_keeps_action_and_log_location(self):
        ui,stream=self.ui()
        view=WorkflowView(ui,STATUS,'automatic','C:/backups/session')
        view.step('manual');view.fail('修补文件不匹配')
        ui.console.print(view.render())
        self.assertIn('修补文件不匹配',stream.getvalue())
        self.assertIn('C:/backups/session',stream.getvalue())
        self.assertEqual(view.states['manual'],'failed')
    def test_manual_file_remains_visible_in_25_row_terminals(self):
        for width in (80,60):
            with self.subTest(width=width):
                ui,stream=self.ui(width,25)
                view=WorkflowView(ui,STATUS,'automatic','sessions/test')
                for step in ('verify','extract','push','manual'):view.step(step)
                view.manual('/sdcard/Download/init_boot_20261015_153000_abcd_stock.img')
                view.event('现在请在手机上操作：\n1. 打开 KernelSU；确认设备受支持。\n2. 安装 -> 选择并修补一个文件。\n3. 选择 Download 中刚传入的 init_boot_20261015_153000_abcd_stock.img。\n4. 修补后保持 USB 连接，自动继续，无需回车。\n不要选择直接安装或安装到另一个槽位。')
                stream.seek(0);stream.truncate(0)
                ui.console.print(view.render())
                lines=stream.getvalue().splitlines()
                self.assertLessEqual(len(lines),25)
                self.assertIn('init_boot_20261015_153000_abcd_stock.img','\n'.join(lines[:25]))
    def test_menu_zero_does_not_connect_or_flash(self):
        ui,stream=self.ui()
        with patch.object(cli,'menu_status',return_value=(None,'未连接')),patch('builtins.input',side_effect=['0']),patch.object(cli,'Bridge') as bridge:
            self.assertEqual(cli.interactive_menu(cli.parser().parse_args([]),ui),0)
            bridge.assert_not_called()
    def test_bad_menu_option_can_retry_then_exit(self):
        ui,stream=self.ui()
        with patch.object(cli,'menu_status',return_value=(None,'未连接')),patch('builtins.input',side_effect=['xyz','','0']):
            self.assertEqual(cli.interactive_menu(cli.parser().parse_args([]),ui),0)
        self.assertIn('无效',stream.getvalue())
    def test_menu_extract_selection_forces_check_mode(self):
        ui,stream=self.ui()
        with patch.object(cli,'menu_status',return_value=(None,'未连接')),patch('builtins.input',side_effect=['3','1','F:/rom.zip','','0']),patch.object(cli,'execute_workflow',return_value=0) as execute:
            self.assertEqual(cli.interactive_menu(cli.parser().parse_args([]),ui),0)
            passed=execute.call_args.args[0]
            self.assertTrue(passed.check)
            self.assertEqual(passed.type,'ota')
            self.assertEqual(passed.source,'F:/rom.zip')
    def test_backups_read_metadata_without_opening_images(self):
        ui,stream=self.ui()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'20261015-test';p.mkdir()
            (p/'session.json').write_text(json.dumps({'status':'failed','phone':STATUS}),encoding='utf-8')
            ui.backups(Path(td))
        self.assertIn('20261015-test',stream.getvalue())
        self.assertIn('失败',stream.getvalue())

if __name__=='__main__':unittest.main()
