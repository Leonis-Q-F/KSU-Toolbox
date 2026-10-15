"""Export actual Rich renderables as SVG (no USB access, illustrative data)."""
import argparse
import io
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rich.console import Console
from rich.cells import cell_len
from rich.terminal_theme import TerminalTheme
from terminal_ui import TerminalUI,WorkflowView,text

THEME=TerminalTheme((15,23,42),(226,232,240),[(15,23,42),(248,113,113),(74,222,128),(250,204,21),(96,165,250),(192,132,252),(34,211,238),(226,232,240)],[(100,116,139),(251,113,133),(134,239,172),(253,224,71),(96,165,250),(216,180,254),(103,232,249),(248,250,252)])
SAMPLE={'model':'Xiaomi 15','device':'dada','version':'OS4.0.0.19.XOCCNXM','locked':'0','state':'unlocked','slot':'b','kernelsu':'已加载'}

def export(path,scene,width=100):
    console=Console(file=io.StringIO(),width=width,height=45,record=True,force_terminal=True,color_system='truecolor',highlight=False,markup=False)
    ui=TerminalUI(console,clear=False)
    if scene=='menu':ui.menu(SAMPLE)
    else:
        view=WorkflowView(ui,SAMPLE,'automatic','sessions / 20261015-示例')
        for step in ('verify','extract','push','manual'):view.step(step)
        view.manual('/sdcard/Download/init_boot_current_stock.img')
        console.print(view.render())
    console.print(text('\n界面预览 · 示例数据 · 本脚本不读取手机','bright_black'))
    svg=console.export_svg(title='KSU Toolbox · '+('主菜单' if scene=='menu' else '等待修补'),theme=THEME)
    svg=re.sub(r'@font-face\s*\{.*?\}', '',svg,flags=re.S)
    svg=svg.replace('font-family: Fira Code, monospace;','font-family: Consolas, "Microsoft YaHei", monospace;')
    # Rich's SVG textLength counts code points; CJK occupies two terminal cells.
    # Correct exported lengths to match the already measured terminal layout.
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    root=ET.fromstring(svg)
    for element in root.iter('{http://www.w3.org/2000/svg}text'):
        content=''.join(element.itertext())
        if content and 'textLength' in element.attrib:
            unit=float(element.attrib['textLength'])/len(content)
            element.set('textLength',str(round(unit*cell_len(content),2)))
            element.set('lengthAdjust','spacingAndGlyphs')
    path.write_text(ET.tostring(root,encoding='unicode'),encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'docs/images')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    export(args.output/'menu.svg','menu')
    export(args.output/'workflow.svg','workflow')
