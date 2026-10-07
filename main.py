# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import ui.res_rc

# 让项目根目录(ui 包)与 src(controller/tools 等)都进入模块搜索路径
_ROOT = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6.QtWidgets import QApplication

from controller_main import MainController

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainController()
    win.show()
    sys.exit(app.exec())
