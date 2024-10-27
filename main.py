# main.py

import sys
import os
import re
import requests
import subprocess
import platform
import shutil
import zipfile
import tarfile
import logging
import traceback
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QProgressBar, QComboBox, QTextBrowser, QInputDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from bs4 import BeautifulSoup

class DownloadThread(QThread):
    progress_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str)
    steamcmd_output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    prompt_signal = pyqtSignal(str, str, dict)
    stopped_signal = pyqtSignal()  # 新增的信号

    def __init__(self, mod_urls, option):
        super().__init__()
        self.mod_urls = mod_urls
        self.option = option
        self.steamcmd_executable = None
        self.steamcmd_dir = None

    def run(self):
        try:
            setup_logging()
            self.steamcmd_executable = check_and_install_steamcmd(self.log_signal)
            self.steamcmd_dir = os.path.dirname(self.steamcmd_executable)

            total_mods = len(self.mod_urls)
            completed_mods = 0

            for index, mod_url in enumerate(self.mod_urls, start=1):
                if self.isInterruptionRequested():
                    break  # 退出循环

                mod_url = mod_url.strip()
                if not mod_url:
                    continue

                self.log_signal.emit(f"\n正在处理第 {index}/{total_mods} 个MOD：{mod_url}")

                # 提取MOD ID
                mod_id = get_mod_id(mod_url, self.log_signal)
                if not mod_id:
                    continue

                # 提取AppID、游戏名称和MOD名称
                app_id, game_name, mod_name = get_app_info(mod_url, mod_id, self.log_signal)
                if not app_id or not game_name or not mod_name:
                    # 如果获取失败，提示用户手动输入
                    result = self.prompt_user_for_app_info(mod_id)
                    if result is None:
                        self.log_signal.emit("用户取消了操作。")
                        continue
                    else:
                        app_id, mod_name = result
                        game_name = "UnknownGame"

                if self.isInterruptionRequested():
                    break  # 再次检查中断请求

                # 下载MOD
                success = download_mod(self.steamcmd_executable, app_id, mod_id, self.log_signal, self.steamcmd_output_signal)
                if not success:
                    continue

                if self.isInterruptionRequested():
                    break  # 再次检查中断请求

                # 移动并重命名MOD文件夹
                moved = move_and_rename_mod_folder(self.steamcmd_dir, app_id, mod_id, game_name, mod_name, self.log_signal)
                if not moved:
                    continue

                completed_mods += 1
                # 更新进度条
                progress_percent = int((completed_mods / total_mods) * 100)
                self.progress_signal.emit(progress_percent)
                self.log_signal.emit(f"已完成 {completed_mods}/{total_mods} 个MOD的下载。")

            self.finished_signal.emit()
        except Exception as e:
            message = f"线程运行中发生异常: {e}"
            if self.log_signal:
                self.log_signal.emit(message)
            logging.error(message, exc_info=True)
        finally:
            self.stopped_signal.emit()

    def prompt_user_for_app_info(self, mod_id):
        """
        提示用户手动输入AppID和MOD名称
        """
        # 发出信号，在主线程中弹出对话框
        response = {}
        self.prompt_signal.emit(mod_id, "无法获取MOD信息，请手动输入AppID和MOD名称：", response)

        # 等待用户输入结果
        while 'app_id' not in response and not self.isInterruptionRequested():
            self.msleep(100)

        if response.get('cancelled', False):
            return None
        else:
            return response['app_id'], response['mod_name']

def setup_logging():
    """
    设置日志记录
    """
    log_dir = os.path.join(os.getcwd(), 'log')
    os.makedirs(log_dir, exist_ok=True)
    log_filename = datetime.now().strftime("download_log_%Y%m%d_%H%M%S.log")
    log_filepath = os.path.join(log_dir, log_filename)
    logging.basicConfig(
        filename=log_filepath,
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.info("日志记录已启动，日志文件：%s", log_filepath)

def get_mod_id(mod_url, log_signal=None):
    """
    从创意工坊的URL中提取MOD ID。
    """
    match = re.search(r'id=(\d+)', mod_url)
    if not match:
        message = f"无法从提供的URL中提取MOD ID：{mod_url}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message)
        return None
    return match.group(1)

def get_app_info(mod_url, mod_id, log_signal=None):
    """
    尝试从MOD页面解析AppID和MOD名称，如果失败则使用Steam API，再次失败则返回None。
    """
    app_id = None
    game_name = None
    mod_name = None

    # 方法1：从MOD页面解析
    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(mod_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 获取游戏名称和AppID
        app_link = soup.find('div', {'class': 'apphub_AppName'})
        if app_link:
            game_name = app_link.text.strip()
        else:
            game_name = "UnknownGame"

        app_id_match = re.search(r'/app/(\d+)', mod_url)
        if app_id_match:
            app_id = app_id_match.group(1)
        else:
            # 尝试从页面的meta信息中获取AppID
            app_id_meta = soup.find('meta', {'name': 'og:url'})
            if app_id_meta and 'content' in app_id_meta.attrs:
                app_id_match = re.search(r'/app/(\d+)', app_id_meta['content'])
                if app_id_match:
                    app_id = app_id_match.group(1)

        # 获取MOD名称
        mod_name_tag = soup.find('div', class_='workshopItemTitle')
        if mod_name_tag:
            mod_name = mod_name_tag.text.strip()
        else:
            mod_name = f"Mod_{mod_id}"

        if app_id and game_name and mod_name:
            return app_id, game_name, mod_name

    except Exception as e:
        message = f"从MOD页面解析信息失败：{e}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)

    # 方法2：使用Steam API
    try:
        # 使用Steam Web API获取MOD详情
        api_url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
        params = {
            'itemcount': 1,
            'publishedfileids[0]': mod_id
        }
        response = requests.post(api_url, data=params)
        response.raise_for_status()
        data = response.json()

        if data and 'response' in data and 'publishedfiledetails' in data['response']:
            details = data['response']['publishedfiledetails'][0]
            app_id = str(details.get('consumer_app_id', ''))
            mod_name = details.get('title', f"Mod_{mod_id}")
            game_name = "UnknownGame"
        else:
            raise Exception("Steam API返回数据无效")

        if app_id and mod_name:
            return app_id, game_name, mod_name

    except Exception as e:
        message = f"使用Steam API获取MOD信息失败：{e}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)

    # 两种方法都失败，返回None
    return None, None, None

def check_and_install_steamcmd(log_signal=None):
    """
    检查SteamCMD是否存在，如果不存在则下载并解压。
    """
    steamcmd_dir = os.path.join(os.getcwd(), 'steamcmd')
    steamcmd_executable = os.path.join(
        steamcmd_dir, 'steamcmd.exe' if platform.system() == 'Windows' else 'steamcmd.sh'
    )

    if not os.path.exists(steamcmd_executable):
        message = "SteamCMD未找到，正在下载..."
        if log_signal:
            log_signal.emit(message)
        logging.info(message)
        os.makedirs(steamcmd_dir, exist_ok=True)

        # 根据操作系统确定下载链接
        if platform.system() == 'Windows':
            url = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip'
            zip_path = os.path.join(steamcmd_dir, 'steamcmd.zip')

            # 下载SteamCMD并显示进度条
            download_file_with_progress(url, zip_path, log_signal)

            # 解压
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(steamcmd_dir)

            os.remove(zip_path)

        elif platform.system() == 'Linux' or platform.system() == 'Darwin':
            url = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz'
            tar_path = os.path.join(steamcmd_dir, 'steamcmd_linux.tar.gz')

            # 下载SteamCMD并显示进度条
            download_file_with_progress(url, tar_path, log_signal)

            # 解压
            with tarfile.open(tar_path, 'r:gz') as tar_ref:
                tar_ref.extractall(steamcmd_dir)

            os.remove(tar_path)

        else:
            message = "不支持的操作系统。"
            if log_signal:
                log_signal.emit(message)
            logging.error(message)
            sys.exit(1)

        message = "SteamCMD下载并解压完成。"
        if log_signal:
            log_signal.emit(message)
        logging.info(message)
    else:
        message = "SteamCMD已存在。"
        if log_signal:
            log_signal.emit(message)
        logging.info(message)

    return steamcmd_executable

def download_file_with_progress(url, dest_path, log_signal=None):
    """
    下载文件，并显示进度条。
    """
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('Content-Length', 0))
            downloaded_size = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        # 打印进度
                        percent = int(downloaded_size * 100 / total_size)
                        if log_signal:
                            log_signal.emit(f"下载进度: {percent}%")
    except requests.RequestException as e:
        message = f"下载失败: {e}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)
        sys.exit(1)

def download_mod(steamcmd_executable, app_id, mod_id, log_signal=None, steamcmd_output_signal=None):
    """
    使用SteamCMD下载MOD，直接显示SteamCMD的输出。
    """
    # 确保steamcmd_executable是可执行的
    if platform.system() != 'Windows':
        os.chmod(steamcmd_executable, 0o755)

    command = [
        steamcmd_executable, "+login", "anonymous",
        "+workshop_download_item", app_id, mod_id,
        "+quit"
    ]

    message = f"开始下载MOD (AppID: {app_id}, MOD ID: {mod_id})..."
    if log_signal:
        log_signal.emit(message)
    logging.info(message)

    try:
        # 设置 encoding='utf-8', errors='ignore'，并使用universal_newlines=True
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1, universal_newlines=True, encoding='utf-8', errors='ignore'
        )

        # 实时读取并处理SteamCMD的输出
        output_line = ''
        while True:
            if process.poll() is not None:
                break
            line = process.stdout.readline()
            if line:
                if steamcmd_output_signal:
                    steamcmd_output_signal.emit(line.strip())
            else:
                break
        process.wait()

        if process.returncode in [0, 6, 7]:
            message = f"MOD (ID: {mod_id}) 下载完成！"
            if log_signal:
                log_signal.emit(message)
            logging.info(message)
            return True
        else:
            message = f"下载失败，退出状态码：{process.returncode}"
            if log_signal:
                log_signal.emit(message)
            logging.error(message)
            return False
    except Exception as e:
        message = f"下载过程中出现异常: {e}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)
        return False

def move_and_rename_mod_folder(steamcmd_dir, app_id, mod_id, game_name, mod_name, log_signal=None):
    """
    移动下载的MOD文件夹到程序当前目录，并重命名为 [游戏名&MOD名]
    """
    source_dir = os.path.join(steamcmd_dir, 'steamapps', 'workshop', 'content', app_id, mod_id)
    if not os.path.exists(source_dir):
        message = "未找到下载的MOD文件夹。"
        if log_signal:
            log_signal.emit(message)
        logging.error(message)
        return False

    # 构造目标文件夹名称
    safe_game_name = re.sub(r'[\/:*?"<>|]', '_', game_name)
    safe_mod_name = re.sub(r'[\/:*?"<>|]', '_', mod_name)
    dest_dir_name = f"[{safe_game_name}&{safe_mod_name}]"
    dest_dir = os.path.join(os.getcwd(), dest_dir_name)

    # 移动并重命名文件夹
    try:
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.move(source_dir, dest_dir)
        message = f"MOD已移动到: {dest_dir}"
        if log_signal:
            log_signal.emit(message)
        logging.info(message)
        return True
    except Exception as e:
        message = f"移动MOD文件夹时出错: {e}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)
        return False

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steam Workshop MOD 下载器")
        self.resize(600, 500)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()

        self.option_label = QLabel("请选择下载方式：")
        main_layout.addWidget(self.option_label)

        self.option_combo = QComboBox()
        self.option_combo.addItems([
            "下载单个MOD",
            "下载多个MOD",
            "从文件读取MOD列表"
        ])
        main_layout.addWidget(self.option_combo)

        self.input_label = QLabel("请输入MOD URL：")
        main_layout.addWidget(self.input_label)

        # 创建输入区域的容器
        self.input_area = QWidget()
        input_layout = QVBoxLayout()
        self.input_area.setLayout(input_layout)
        main_layout.addWidget(self.input_area)

        # 创建两个输入控件
        self.single_mod_input = QLineEdit()
        input_layout.addWidget(self.single_mod_input)

        self.multi_mod_input = QTextEdit()
        self.multi_mod_input.setFixedHeight(100)
        self.multi_mod_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.multi_mod_input.setAcceptRichText(False)  # 只接受纯文本，防止粘贴时解析富文本
        self.multi_mod_input.setVisible(False)
        input_layout.addWidget(self.multi_mod_input)

        self.file_button = QPushButton("选择MOD列表文件")
        self.file_button.clicked.connect(self.select_file)
        self.file_button.setVisible(False)
        input_layout.addWidget(self.file_button)

        self.start_button = QPushButton("开始下载")
        self.start_button.clicked.connect(self.start_download)
        main_layout.addWidget(self.start_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.dynamic_output_label = QLabel()
        main_layout.addWidget(self.dynamic_output_label)

        self.log_text = QTextBrowser()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text)

        self.setLayout(main_layout)

        # 根据选项调整界面元素
        self.option_combo.currentIndexChanged.connect(self.update_ui)

    def update_ui(self, index):
        # 记录当前输入内容
        if index == 0:  # 下载单个MOD
            if self.multi_mod_input.isVisible():
                self.single_mod_input.setText(self.multi_mod_input.toPlainText().splitlines()[0] if self.multi_mod_input.toPlainText() else '')
        elif index == 1:  # 下载多个MOD
            if self.single_mod_input.isVisible():
                self.multi_mod_input.setPlainText(self.single_mod_input.text())

        if index == 2:  # 从文件读取MOD列表
            self.input_label.setVisible(False)
            self.single_mod_input.setVisible(False)
            self.multi_mod_input.setVisible(False)
            self.file_button.setVisible(True)
        else:
            self.input_label.setVisible(True)
            self.file_button.setVisible(False)
            if index == 0:
                self.input_label.setText("请输入MOD URL：")
                self.single_mod_input.setVisible(True)
                self.multi_mod_input.setVisible(False)
            elif index == 1:
                self.input_label.setText("请输入MOD URL（每行一个）：")
                self.single_mod_input.setVisible(False)
                self.multi_mod_input.setVisible(True)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择MOD列表文件", "", "文本文件 (*.txt)")
        if file_path:
            self.single_mod_input.setText(file_path)

    def start_download(self):
        option = self.option_combo.currentIndex()
        if option == 2:  # 从文件读取MOD列表
            file_path = self.single_mod_input.text().strip()
            if not file_path or not os.path.isfile(file_path):
                QMessageBox.warning(self, "错误", "请选择有效的MOD列表文件。")
                return
            with open(file_path, 'r') as f:
                mod_urls = f.read().splitlines()
                mod_urls = [url.strip() for url in mod_urls if url.strip()]
                if not mod_urls:
                    QMessageBox.warning(self, "错误", "MOD列表文件为空或格式不正确。")
                    return
        elif option == 0:  # 下载单个MOD
            mod_url = self.single_mod_input.text().strip()
            if not mod_url:
                QMessageBox.warning(self, "错误", "请输入MOD的URL。")
                return
            mod_urls = [mod_url]
        else:  # 下载多个MOD
            mod_urls_input = self.multi_mod_input.toPlainText().strip()
            if not mod_urls_input:
                QMessageBox.warning(self, "错误", "请输入MOD的URL。")
                return
            mod_urls = mod_urls_input.splitlines()
            mod_urls = [url.strip() for url in mod_urls if url.strip()]

        # 禁用输入控件
        self.disable_inputs()

        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.dynamic_output_label.clear()

        self.thread = DownloadThread(mod_urls, option)
        self.thread.progress_signal.connect(self.update_progress)
        self.thread.log_signal.connect(self.update_log)
        self.thread.steamcmd_output_signal.connect(self.update_steamcmd_output)
        self.thread.finished_signal.connect(self.download_finished)
        self.thread.prompt_signal.connect(self.prompt_for_app_info)
        self.thread.stopped_signal.connect(self.cleanup_after_thread)  # 新增的连接
        self.thread.start()

    def disable_inputs(self):
        """
        禁用输入控件，并添加半透明遮罩
        """
        self.option_combo.setEnabled(False)
        self.single_mod_input.setEnabled(False)
        self.multi_mod_input.setEnabled(False)
        self.file_button.setEnabled(False)
        self.start_button.setEnabled(False)

        # 添加遮罩到输入区域
        self.input_overlay = QWidget(self.input_area)
        self.input_overlay.setGeometry(self.input_area.rect())
        self.input_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 50%);")
        self.input_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.input_overlay.show()

    def enable_inputs(self):
        """
        启用输入控件，移除遮罩
        """
        self.option_combo.setEnabled(True)
        self.single_mod_input.setEnabled(True)
        self.multi_mod_input.setEnabled(True)
        self.file_button.setEnabled(True)
        self.start_button.setEnabled(True)

        if hasattr(self, 'input_overlay'):
            self.input_overlay.hide()
            del self.input_overlay

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_log(self, message):
        self.log_text.append(message)

    def update_steamcmd_output(self, message):
        self.dynamic_output_label.setText(message)

    def download_finished(self):
        QMessageBox.information(self, "提示", "所有操作完成。")
        self.enable_inputs()

    def prompt_for_app_info(self, mod_id, message, response):
        """
        弹出对话框，提示用户输入AppID和MOD名称
        """
        app_id, ok1 = QInputDialog.getText(self, "需要输入AppID", f"无法自动获取MOD (ID: {mod_id}) 的AppID。\n请手动输入AppID：")
        if not ok1 or not app_id.strip():
            response['cancelled'] = True
            return
        mod_name, ok2 = QInputDialog.getText(self, "需要输入MOD名称", "请输入MOD的名称：")
        if not ok2 or not mod_name.strip():
            response['cancelled'] = True
            return
        response['app_id'] = app_id.strip()
        response['mod_name'] = mod_name.strip()

    def cleanup_after_thread(self):
        """
        在线程停止后，执行清理操作
        """
        self.enable_inputs()

    def closeEvent(self, event):
        """
        在关闭窗口时，尝试安全地终止线程，并释放资源
        """
        if hasattr(self, 'thread') and self.thread.isRunning():
            reply = QMessageBox.question(
                self, "提示", "当前有任务正在运行，是否立即退出？未完成的下载将被中断。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # 请求线程中断
                self.thread.requestInterruption()
                # 禁用窗口以防止重复操作
                self.setEnabled(False)
                # 等待线程结束
                self.thread.stopped_signal.connect(self.cleanup_and_exit)
                event.ignore()
            else:
                event.ignore()
        else:
            event.accept()

    def cleanup_and_exit(self):
        """
        清理资源并退出程序
        """
        if hasattr(self, 'thread'):
            self.thread.quit()
            self.thread.wait()
        QApplication.instance().quit()

def main():
    app = QApplication(sys.argv)
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print("发生异常：", e)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
