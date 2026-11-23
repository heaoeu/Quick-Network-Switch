# -*- coding: utf-8 -*-
# 由 --install 生成；路径相对于本文件，移动项目后仍可用。
import os
import runpy
import subprocess
import sys
sys.dont_write_bytecode = True
PROJECT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(PROJECT, "net_switch.py")
MODE = '--manage'
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)
APP_EXE = ''
try:
    from netswitch.win32 import ensure_app_executable
    APP_EXE = ensure_app_executable()
except Exception:
    pass
if APP_EXE and os.path.isfile(APP_EXE) and os.path.normcase(os.path.abspath(APP_EXE)) != os.path.normcase(os.path.abspath(sys.executable)):
    try:
        subprocess.Popen([APP_EXE, SCRIPT, MODE], cwd=PROJECT, creationflags=0x08000000, close_fds=True)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass
sys.argv = [SCRIPT, MODE]
runpy.run_path(SCRIPT, run_name='__main__')
