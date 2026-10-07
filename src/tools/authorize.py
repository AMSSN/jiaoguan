from PyQt6.QtWidgets import *
from PyQt6.QtGui import *
from PyQt6.QtCore import *
import wmi
import base64
from pyDes import *
from datetime import datetime
import json
import pythoncom


def get_CPU_info():
    cpu = []
    pythoncom.CoInitialize()
    s = wmi.WMI()
    cp = s.Win32_Processor()
    for u in cp:
        cpu.append(
            {
                "Name": u.Name,
                "Serial Number": u.ProcessorId,
                "CoreNum": u.NumberOfCores
            }
        )
    pythoncom.CoUninitialize()
    return cpu


def get_disk_info():
    disk = []
    pythoncom.CoInitialize()
    s = wmi.WMI()
    for pd in s.Win32_DiskDrive():
        disk.append(
            {
                "Serial": s.Win32_PhysicalMedia()[0].SerialNumber.lstrip().rstrip(),  # 获取硬盘序列号，调用另外一个win32 API
                "ID": pd.deviceid,
                "Caption": pd.Caption,
                "size": str(int(float(pd.Size) / 1024 / 1024 / 1024))
            }
        )
    pythoncom.CoUninitialize()
    return disk


def get_network_info():
    network = []
    pythoncom.CoInitialize()
    s = wmi.WMI()
    for nw in s.Win32_NetworkAdapterConfiguration():
        if nw.MacAddress != None:
            network.append(
                {
                    "MAC": nw.MacAddress,
                    "ip": nw.IPAddress
                }
            )
    pythoncom.CoUninitialize()
    return network


def get_mainboard_info():
    mainboard = []
    pythoncom.CoInitialize()
    s = wmi.WMI()
    for board_id in s.Win32_BaseBoard():
        mainboard.append(board_id.SerialNumber.strip().strip('.'))
    pythoncom.CoUninitialize()
    return mainboard


def generate_machine_code():
    a = get_network_info()
    b = get_CPU_info()
    c = get_disk_info()
    d = get_mainboard_info()
    machinecode_str = a[0]['MAC'] + b[0]['Serial Number'] + c[0]['Serial'] + d[0]
    selectIndex = [3, 6, 15, 16, 17, 30, 32, 38, 43, 46, 54, 55]
    macode = ""
    for i in selectIndex:
        macode = macode + machinecode_str[i]
    return macode


def CodeDecryted(EncryptStr):
    try:
        bas1 = base64.b32decode(EncryptStr)
    except Exception as e:
        print('注册码无效！')
        return '0000'
    key = '3ef25a8n'
    iv = '477bdb68'
    k = des(key, CBC, iv, pad=None, padmode=PAD_PKCS5)
    byte_code = k.decrypt(bas1)
    code = str(byte_code).replace("b'", '').replace("'", '')
    return code


class MachineCodeThread(QThread):
    finished_signal = pyqtSignal(str)

    def __init__(self):
        super(MachineCodeThread, self).__init__()

    def run(self):
        try:
            machine_code = generate_machine_code()
            self.finished_signal.emit(machine_code)
        except Exception as e:
            self.finished_signal.emit(f"生成机器码时出现错误: {str(e)}")


class ActivationDialog(QDialog):
    """软件激活对话框"""

    # 定义激活成功信号
    activation_success = pyqtSignal(str)

    def __init__(self, parent=None, machine_code=None):
        super().__init__(parent)
        self.parent = parent
        self.machine_code = machine_code

        self.label_style = "font-family: 'Microsoft YaHei'; font-size: 14px; font-weight: bold;"
        self.lineEdit_style = """
                    QLineEdit {
                        border: 1px solid #cccccc;
                        border-radius: 3px;
                        padding: 8px;
                        font-family: 'Microsoft YaHei';
                        font-size: 14px;
                        background-color: white;
                    }
                    QLineEdit:focus {
                        border: 1px solid #a5a09f;
                    }
                """
        self.textEdit_style = """
                    QTextEdit {
                        border: 1px solid #cccccc;
                        border-radius: 3px;
                        padding: 5px;
                        font-family: 'Microsoft YaHei';
                        font-size: 14px;
                        background-color: white;
                    }
                """

        self.button_style = """
                    QPushButton {
                        background-color: #e1dddc;
                        color: black;
                        border: none;
                        border-radius: 5px;
                        font-size: 16px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #c6c1bf;
                    }
                    QPushButton:pressed {
                        background-color: #a5a09f;
                    }
                """

        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle('软件激活')
        self.setFixedSize(400, 300)
        self.setModal(True)
        self.setWindowIcon(QIcon.fromTheme('dialog-password'))

        layout_main = QVBoxLayout()

        label_title = QLabel('请发送(机器码)给管理员获得(注册码)')
        label_title.setAlignment(Qt.AlignCenter)
        label_title.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #2c3e50;
                padding: 10px;
            }
        """)

        spacer1 = QSpacerItem(50, 10, QSizePolicy.Minimum, QSizePolicy.Expanding)
        spacer2 = QSpacerItem(50, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)

        # 机器码
        self.label_machine = QLabel('机器码', self)
        self.label_machine.setFixedSize(50, 35)
        self.label_machine.setStyleSheet(self.label_style)
        self.lineEdit_machine = QLineEdit(self)
        self.lineEdit_machine.setFixedSize(200, 35)
        self.lineEdit_machine.setStyleSheet(self.lineEdit_style)
        self.lineEdit_machine.setText(self.machine_code)
        layout_machine = QHBoxLayout()
        layout_machine.addStretch(1)
        layout_machine.addWidget(self.label_machine)
        layout_machine.addWidget(self.lineEdit_machine)
        layout_machine.addStretch(1)

        # 注册码
        self.label_register = QLabel('注册码', self)
        self.label_register.setFixedSize(50, 35)
        self.label_register.setStyleSheet(self.label_style)
        self.textEdit_register = QTextEdit(self)
        self.textEdit_register.setFixedSize(200, 70)
        self.textEdit_register.setStyleSheet(self.textEdit_style)
        layout_register = QHBoxLayout()
        layout_register.addStretch(1)
        layout_register.addWidget(self.label_register)
        layout_register.addWidget(self.textEdit_register)
        layout_register.addStretch(1)

        # 激活按钮
        self.button_activate = QPushButton('注册激活')
        self.button_activate.setFixedSize(100, 40)
        self.button_activate.setStyleSheet(self.button_style)
        layout_button = QHBoxLayout()
        layout_button.addStretch(1)
        layout_button.addWidget(self.button_activate)
        layout_button.addStretch(1)

        layout_main.addItem(spacer1)
        layout_main.addWidget(label_title)
        layout_main.addItem(spacer1)
        layout_main.addLayout(layout_machine)
        layout_main.addLayout(layout_register)
        layout_main.addItem(spacer2)
        layout_main.addLayout(layout_button)
        layout_main.addStretch(1)

        self.setLayout(layout_main)

        self.button_activate.clicked.connect(self.activate_and_verify)

    def activate_and_verify(self):
        machine_code = self.lineEdit_machine.text()
        register_code = self.textEdit_register.toPlainText()
        dereg_code = CodeDecryted(register_code)
        # print(dereg_code)
        if machine_code not in dereg_code:
            result = QMessageBox.warning(self, '警告', '注册码无效，请输入正确的注册码', QMessageBox.Ok)
            self.textEdit_register.clear()
        else:
            expire_time = dereg_code.replace(machine_code, '')
            current_time = datetime.now()
            current_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
            if expire_time is None:
                result = QMessageBox.warning(self, '警告', '注册码无效，请输入正确的注册码', QMessageBox.Ok)
                self.textEdit_register.clear()
            elif expire_time < current_time:
                result = QMessageBox.warning(self, '警告', '注册码过期，请联系管理员获取最新注册码', QMessageBox.Ok)
                self.textEdit_register.clear()
            else:
                result = QMessageBox.information(self, '提示', '注册成功，请重新打开软件', QMessageBox.Ok)
                license_data = {
                    "generate_time": current_time,
                    "expire_time": expire_time,
                    "machine_code": machine_code,
                    "register_code": register_code,
                }
                with open("license.lc", 'w', encoding='utf-8') as f:
                    json.dump(license_data, f, ensure_ascii=False, indent=2)
