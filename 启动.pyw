# -*- coding: utf-8 -*-
# 由 --install 生成；桌面文件链接指向此文件。
import os
import runpy
import subprocess
import sys
sys.dont_write_bytecode = True
PROJECT = 'C:\\Users\\HY\\Documents\\deepseek-harness\\default-workspace\\net-switch'
os.chdir(PROJECT)
SCRIPT = 'C:\\Users\\HY\\Documents\\deepseek-harness\\default-workspace\\net-switch\\net_switch.py'
MODE = '--manage'
APP_EXE = 'D:\\Develop\\Python\\python\\网络快捷切换.exe'
if os.path.isfile(APP_EXE) and os.path.normcase(os.path.basename(sys.executable)) != os.path.normcase(os.path.basename(APP_EXE)):
    try:
        subprocess.Popen([APP_EXE, SCRIPT, MODE], cwd=PROJECT, creationflags=0x08000000, close_fds=True)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass
sys.argv = [SCRIPT, MODE]
runpy.run_path(SCRIPT, run_name='__main__')
