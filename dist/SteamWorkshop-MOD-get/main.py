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
from configparser import ConfigParser
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QProgressBar, QComboBox, QTextBrowser,
    QInputDialog, QHBoxLayout, QAction, QMenuBar, QMenu
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon
from bs4 import BeautifulSoup

# 全局变量
SETTINGS = {}

# 默认设置
DEFAULT_SETTINGS = {
    'download_method': 'SteamCMD',
    'steam_username': 'anonymous',
    'steam_password': '',
    'language': 'Chinese',  # 'Chinese' 或 'English'
    'login_method': 'anonymous'  # 'anonymous' 或 'account'
}

# 配置文件路径
CONFIG_FILE = 'config.ini'

# 翻译字典
TRANSLATIONS = {}

# 语言文件路径
LANG_FILE = 'lang.txt'

def load_settings():
    config = ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        # 如果配置文件不存在，创建默认配置文件
        config['Settings'] = DEFAULT_SETTINGS
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
        SETTINGS.update(DEFAULT_SETTINGS)
    else:
        config.read(CONFIG_FILE, encoding='utf-8')
        if 'Settings' in config.sections():
            for key in DEFAULT_SETTINGS:
                SETTINGS[key] = config.get('Settings', key, fallback=DEFAULT_SETTINGS[key])
        else:
            # 如果配置文件中没有 'Settings' 部分，使用默认设置
            SETTINGS.update(DEFAULT_SETTINGS)

def save_settings():
    config = ConfigParser()
    config['Settings'] = SETTINGS
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        config.write(f)

def load_translations():
    config = ConfigParser(interpolation=None)  # 禁用插值功能
    if not os.path.exists(LANG_FILE):
        # 如果 lang.txt 不存在，提示错误
        print(f"错误：未找到 {LANG_FILE}。")
        sys.exit(1)
    else:
        config.read(LANG_FILE, encoding='utf-8')
        for section in config.sections():
            TRANSLATIONS[section] = {}
            for key in config[section]:
                TRANSLATIONS[section][key] = config[section][key]

def tr(key, **kwargs):
    """根据当前语言设置翻译给定的键。"""
    language = SETTINGS.get('language', 'Chinese')
    text = TRANSLATIONS.get(language, TRANSLATIONS['Chinese']).get(key, key)
    return text.format(**kwargs)

class DownloadThread(QThread):
    progress_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str)
    steamcmd_output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    prompt_signal = pyqtSignal(str, str, dict)
    stopped_signal = pyqtSignal()  # 线程完成的信号

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

                self.log_signal.emit(tr('mod_processing', index=index, total=total_mods, mod_url=mod_url))

                # 提取 MOD ID
                mod_id = get_mod_id(mod_url, self.log_signal)
                if not mod_id:
                    continue

                # 提取 AppID、游戏名称和 MOD 名称
                app_id, game_name, mod_name = get_app_info(mod_url, mod_id, self.log_signal)
                if not app_id or not game_name or not mod_name:
                    # 如果获取失败，提示用户手动输入
                    result = self.prompt_user_for_app_info(mod_id)
                    if result is None:
                        self.log_signal.emit(tr('user_canceled_operation'))
                        continue
                    else:
                        app_id, mod_name = result
                        game_name = "UnknownGame"

                if self.isInterruptionRequested():
                    break  # 再次检查中断请求

                # 下载 MOD
                success = download_mod(
                    self.steamcmd_executable,
                    app_id,
                    mod_id,
                    self.log_signal,
                    self.steamcmd_output_signal
                )
                if not success:
                    continue

                if self.isInterruptionRequested():
                    break  # 再次检查中断请求

                # 移动并重命名 MOD 文件夹
                moved = move_and_rename_mod_folder(
                    self.steamcmd_dir,
                    app_id,
                    mod_id,
                    game_name,
                    mod_name,
                    self.log_signal
                )
                if not moved:
                    continue

                completed_mods += 1
                # 更新进度条
                progress_percent = int((completed_mods / total_mods) * 100)
                self.progress_signal.emit(progress_percent)
                self.log_signal.emit(tr('mods_completed', completed=completed_mods, total=total_mods))

            self.finished_signal.emit()
        except Exception as e:
            message = f"{tr('error')}: {e}"
            if self.log_signal:
                self.log_signal.emit(message)
            logging.error(message, exc_info=True)
        finally:
            self.stopped_signal.emit()

    def prompt_user_for_app_info(self, mod_id):
        """
        提示用户手动输入 AppID 和 MOD 名称。
        """
        # 发出信号，在主线程中弹出对话框
        response = {}
        self.prompt_signal.emit(mod_id, tr("cannot_get_mod_info"), response)

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
    if not os.path.exists('log'):
        os.makedirs('log')
    log_filename = datetime.now().strftime('log/log_%Y%m%d_%H%M%S.txt')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_filename,
        filemode='w',
        encoding='utf-8'
    )
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    print(tr('logging_started', log_filepath=log_filename))

def get_mod_id(mod_url, log_signal=None):
    """
    从创意工坊的URL中提取MOD ID。
    """
    match = re.search(r'id=(\d+)', mod_url)
    if not match:
        message = f"{tr('cannot_extract_mod_id')}: {mod_url}"
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
        message = f"{tr('parse_mod_page_failed')}: {e}"
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
            raise Exception(tr('invalid_steam_api_response'))

        if app_id and mod_name:
            return app_id, game_name, mod_name

    except Exception as e:
        message = f"{tr('steam_api_failed')}: {e}"
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
        message = tr("steamcmd_not_found_downloading")
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
            message = tr("unsupported_os")
            if log_signal:
                log_signal.emit(message)
            logging.error(message)
            sys.exit(1)

        message = tr("steamcmd_downloaded")
        if log_signal:
            log_signal.emit(message)
        logging.info(message)
    else:
        message = tr("steamcmd_exists")
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
                            log_signal.emit(tr('download_progress', percent=percent))
    except requests.RequestException as e:
        message = f"{tr('download_failed')}: {e}"
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)
        sys.exit(1)

def download_mod(steamcmd_executable, app_id, mod_id, log_signal=None, steamcmd_output_signal=None):
    """
    使用 SteamCMD 下载 MOD，直接显示 SteamCMD 的输出。
    """
    # 确保 steamcmd_executable 是可执行的
    if platform.system() != 'Windows':
        os.chmod(steamcmd_executable, 0o755)

    # 准备命令
    command = [
        steamcmd_executable, "+login"
    ]

    # 使用提供的凭据或匿名
    if SETTINGS.get('login_method', 'anonymous') == 'account':
        command.extend([SETTINGS.get('steam_username'), SETTINGS.get('steam_password')])
    else:
        command.append('anonymous')

    command.extend([
        "+workshop_download_item", app_id, mod_id,
        "+quit"
    ])

    message = tr('start_download_mod', app_id=app_id, mod_id=mod_id)
    if log_signal:
        log_signal.emit(message)
    logging.info(message)

    try:
        # 设置 encoding='utf-8', errors='ignore'，并使用 universal_newlines=True
        # 添加 creationflags 参数以隐藏窗口
        if platform.system() == 'Windows':
            creationflags = subprocess.CREATE_NO_WINDOW
        else:
            creationflags = 0  # 非 Windows 系统无需设置

        # 初始化 SteamCMD 输出缓存
        steamcmd_output = []

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creationflags  # 添加此参数
        )

        # 实时读取并处理 SteamCMD 的输出
        while True:
            if process.poll() is not None:
                break
            line = process.stdout.readline()
            if line:
                steamcmd_output.append(line.strip())  # 记录输出
                if steamcmd_output_signal:
                    steamcmd_output_signal.emit(line.strip())
                if "Steam Guard" in line and "code" in line:
                    # 需要输入 Steam Guard 代码
                    code, ok = QInputDialog.getText(None, tr('prompt'), tr('enter_steam_guard_code'))
                    if ok and code:
                        process.stdin.write(code + '\n')
                        process.stdin.flush()
                    else:
                        process.kill()
                        return False
            else:
                break
        process.wait()

        if process.returncode in [0, 6, 7]:
            message = tr('mod_downloaded', mod_id=mod_id)
            if log_signal:
                log_signal.emit(message)
            logging.info(message)
            return True
        else:
            # 下载失败，输出 SteamCMD 的结果并给出建议
            steamcmd_output_text = '\n'.join(steamcmd_output)
            if log_signal:
                log_signal.emit(tr('download_failed_exit_code', code=process.returncode))
                log_signal.emit(tr('steamcmd_output') + ':\n' + steamcmd_output_text)
            logging.error(tr('download_failed_exit_code', code=process.returncode))
            logging.error(tr('steamcmd_output') + ':\n' + steamcmd_output_text)

            # 分析 SteamCMD 输出并给出建议
            suggestion = analyze_steamcmd_output(steamcmd_output_text)
            if suggestion and log_signal:
                log_signal.emit(tr('suggestion') + ': ' + suggestion)
            return False
    except Exception as e:
        message = tr('download_exception', exception=e)
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)
        return False

def analyze_steamcmd_output(output_text):
    """
    分析 SteamCMD 的输出，返回针对用户的建议。
    """
    if "No subscription" in output_text:
        return tr('suggestion_no_subscription')
    elif "Invalid Password" in output_text:
        return tr('suggestion_invalid_password')
    elif "Too many login failures" in output_text:
        return tr('suggestion_too_many_failures')
    elif "Logged in OK" in output_text and "Downloading item" in output_text and "ERROR!" in output_text:
        return tr('suggestion_private_or_removed_mod')
    elif "Invalid AuthCode" in output_text or "Two-factor code mismatch" in output_text:
        return tr('suggestion_invalid_steam_guard_code')
    else:
        return tr('suggestion_general_failure')


def move_and_rename_mod_folder(steamcmd_dir, app_id, mod_id, game_name, mod_name, log_signal=None):
    """
    移动下载的MOD文件夹到程序当前目录，并重命名为 [游戏名&MOD名]
    """
    source_dir = os.path.join(steamcmd_dir, 'steamapps', 'workshop', 'content', app_id, mod_id)
    if not os.path.exists(source_dir):
        message = tr('mod_folder_not_found')
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
        message = tr('mod_moved_to', dest_dir=dest_dir)
        if log_signal:
            log_signal.emit(message)
        logging.info(message)
        return True
    except Exception as e:
        message = tr('move_mod_error', error=e)
        if log_signal:
            log_signal.emit(message)
        logging.error(message, exc_info=True)
        return False

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr('app_title'))
        self.resize(600, 500)
        self.setWindowIcon(QIcon('logo.ico'))  # 设置窗口图标

        # 初始化主题（默认使用明亮主题）
        self.current_theme = 'light'
        self.light_theme_stylesheet = """
        /* 明亮主题样式 */
        """
        self.dark_theme_stylesheet = """
        /* 暗黑主题样式 */
        QWidget {
            background-color: #2E2E2E;
            color: #FFFFFF;
        }
        /* ...（其他样式保持不变） */
        """
        self.init_ui()
        self.apply_theme(self.current_theme)

    def init_ui(self):
        main_layout = QVBoxLayout()

        # 初始化菜单栏
        menubar = QMenuBar(self)

        # 主题菜单（放在前面）
        theme_menu = menubar.addMenu(tr('theme'))

        # 主题切换动作，使用图标表示
        self.switch_theme_action = QAction('☀', self)
        self.switch_theme_action.triggered.connect(self.switch_theme)
        theme_menu.addAction(self.switch_theme_action)

        # 设置菜单（放在后面）
        settings_menu = menubar.addMenu(tr('settings'))

        # 设置下载方式
        set_download_method_action = QAction(tr('set_download_method'), self)
        set_download_method_action.triggered.connect(self.set_download_method)
        settings_menu.addAction(set_download_method_action)

        # 设置登录方式
        set_login_method_action = QAction(tr('select_login_method'), self)
        set_login_method_action.triggered.connect(self.set_login_method)
        settings_menu.addAction(set_login_method_action)

        # 恢复默认设置
        reset_settings_action = QAction(tr('reset_settings'), self)
        reset_settings_action.triggered.connect(self.reset_settings)
        settings_menu.addAction(reset_settings_action)

        # 更改语言
        change_language_action = QAction(tr('change_language'), self)
        change_language_action.triggered.connect(self.change_language)
        settings_menu.addAction(change_language_action)

        # 添加“帮助”菜单
        help_menu = menubar.addMenu(tr('help'))

        # 添加“查看常见问题”动作
        view_help_action = QAction(tr('view_help'), self)
        view_help_action.triggered.connect(self.view_help)
        help_menu.addAction(view_help_action)

        main_layout.setMenuBar(menubar)

        self.option_label = QLabel(tr("download_method") + "：")
        main_layout.addWidget(self.option_label)

        self.option_combo = QComboBox()
        self.option_combo.addItems([
            tr("download_single_mod"),
            tr("download_multiple_mods"),
            tr("download_from_file")
        ])
        main_layout.addWidget(self.option_combo)

        self.input_label = QLabel(tr("enter_mod_url"))
        main_layout.addWidget(self.input_label)

        # 输入区域容器
        self.input_area = QWidget()
        input_layout = QVBoxLayout()
        self.input_area.setLayout(input_layout)
        main_layout.addWidget(self.input_area)

        # 单个 MOD 输入
        self.single_mod_input = QLineEdit()
        input_layout.addWidget(self.single_mod_input)

        # 多个 MOD 输入
        self.multi_mod_input = QTextEdit()
        self.multi_mod_input.setFixedHeight(100)
        self.multi_mod_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.multi_mod_input.setAcceptRichText(False)
        self.multi_mod_input.setVisible(False)
        input_layout.addWidget(self.multi_mod_input)

        # 文件选择按钮
        self.file_button = QPushButton(tr("select_mod_list_file"))
        self.file_button.clicked.connect(self.select_file)
        self.file_button.setVisible(False)
        input_layout.addWidget(self.file_button)

        self.start_button = QPushButton(tr("start_download"))
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

    def view_help(self):
        """
        显示常见问题和解决方案
        """
        help_text = tr('help_content')
        QMessageBox.information(self, tr('help'), help_text)

    def set_download_method(self):
        """
        设置下载方式（目前只有 SteamCMD，可扩展）。
        """
        methods = ['SteamCMD']  # 未来可扩展
        method, ok = QInputDialog.getItem(self, tr('set_download_method'), tr('download_method') + '：', methods, 0, False)
        if ok and method:
            SETTINGS['download_method'] = method
            QMessageBox.information(self, tr('info'), f"{tr('download_method_set')} {method}。")
            save_settings()

    def set_login_method(self):
        """
        设置登录方式
        """
        methods = [tr('login_anonymous'), tr('login_steam_account')]
        method, ok = QInputDialog.getItem(self, tr('select_login_method'), tr('download_method') + '：', methods, 0, False)
        if ok and method:
            if method == tr('login_anonymous'):
                SETTINGS['login_method'] = 'anonymous'
                SETTINGS['steam_username'] = 'anonymous'
                SETTINGS['steam_password'] = ''
                QMessageBox.information(self, tr('info'), f"{tr('download_method_set')} {tr('login_anonymous')}")
            else:
                SETTINGS['login_method'] = 'account'
                self.set_steam_credentials()
            save_settings()

    def set_steam_credentials(self):
        """
        设置 SteamCMD 登录凭据
        """
        username, ok1 = QInputDialog.getText(self, tr('set_steam_credentials'), tr('enter_steam_username'), QLineEdit.Normal, SETTINGS.get('steam_username', ''))
        if not ok1:
            return

        username = username.strip()
        if username == '':
            QMessageBox.warning(self, tr('warning'), tr('username_empty'))
            return

        password, ok2 = QInputDialog.getText(self, tr('set_steam_credentials'), tr('enter_steam_password'), QLineEdit.Password)
        if not ok2:
            return
        password = password.strip()
        if password == '':
            QMessageBox.warning(self, tr('warning'), tr('password_empty'))
            return
        SETTINGS['steam_username'] = username
        SETTINGS['steam_password'] = password

        QMessageBox.information(self, tr('info'), tr('steam_credentials_updated'))
        save_settings()

    def change_language(self):
        """
        更改应用程序语言。
        """
        languages = ['Chinese', 'English']
        language_names = ['中文', 'English']
        current_language = SETTINGS.get('language', 'Chinese')
        current_index = languages.index(current_language)
        language_name, ok = QInputDialog.getItem(self, tr('change_language'), tr('language') + '：', language_names, current_index, False)
        if ok and language_name:
            selected_language = languages[language_names.index(language_name)]
            if selected_language != current_language:
                SETTINGS['language'] = selected_language
                save_settings()
                QMessageBox.information(self, tr('info'), tr('language_changed'))
                # 刷新所有 UI 文本
                self.refresh_ui_texts()

    def reset_settings(self):
        """
        恢复默认设置
        """
        reply = QMessageBox.question(
            self, tr("prompt"), tr("settings_reset") + "?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            SETTINGS.update(DEFAULT_SETTINGS)
            save_settings()
            QMessageBox.information(self, tr('info'), tr('settings_reset'))
            self.refresh_ui_texts()

    def refresh_ui_texts(self):
        """
        刷新所有 UI 文本以匹配当前语言。
        """
        self.setWindowTitle(tr('app_title'))
        self.option_label.setText(tr("download_method") + "：")
        self.option_combo.setItemText(0, tr("download_single_mod"))
        self.option_combo.setItemText(1, tr("download_multiple_mods"))
        self.option_combo.setItemText(2, tr("download_from_file"))
        self.input_label.setText(tr("enter_mod_url"))
        self.file_button.setText(tr("select_mod_list_file"))
        self.start_button.setText(tr("start_download"))
        # 更新菜单文本
        self.update_menu_texts()

    def update_menu_texts(self):
        """
        更新菜单文本以匹配当前语言。
        """
        menubar = self.findChild(QMenuBar)
        if menubar:
            # 更新主题菜单（第一个）
            theme_menu = menubar.actions()[0].menu()
            if theme_menu:
                theme_menu.setTitle(tr('theme'))
                theme_menu.actions()[0].setText(self.switch_theme_action.text())  # 图标文本已在切换时更新

            # 更新设置菜单（第二个）
            settings_menu = menubar.actions()[1].menu()
            if settings_menu:
                settings_menu.setTitle(tr('settings'))
                actions = settings_menu.actions()
                actions[0].setText(tr('set_download_method'))
                actions[1].setText(tr('select_login_method'))
                actions[2].setText(tr('reset_settings'))
                actions[3].setText(tr('change_language'))

            # 更新帮助菜单（第三个）
            help_menu = menubar.actions()[2].menu()
            if help_menu:
                help_menu.setTitle(tr('help'))
                help_menu.actions()[0].setText(tr('view_help'))

    def switch_theme(self):
        """
        切换明暗主题，使用图案表示
        """
        if self.current_theme == 'light':
            self.current_theme = 'dark'
            self.switch_theme_action.setText('☾')  # 月亮图标
        else:
            self.current_theme = 'light'
            self.switch_theme_action.setText('☀')  # 太阳图标
        self.apply_theme(self.current_theme)

    def apply_theme(self, theme):
        """
        应用指定的主题
        """
        if theme == 'light':
            self.setStyleSheet("")  # 重置为默认样式
        elif theme == 'dark':
            self.setStyleSheet(self.dark_theme_stylesheet)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, tr("select_mod_list_file"), "", tr("Text Files (*.txt)"))
        if file_path:
            self.single_mod_input.setText(file_path)

    def start_download(self):
        option = self.option_combo.currentIndex()
        if option == 2:  # 从文件读取 MOD 列表
            file_path = self.single_mod_input.text().strip()
            if not file_path or not os.path.isfile(file_path):
                QMessageBox.warning(self, tr("error"), tr("请选择有效的 MOD 列表文件。"))
                return
            with open(file_path, 'r', encoding='utf-8') as f:
                mod_urls = f.read().splitlines()
                mod_urls = [url.strip() for url in mod_urls if url.strip()]
                if not mod_urls:
                    QMessageBox.warning(self, tr("error"), tr("MOD 列表文件为空或格式不正确。"))
                    return
        elif option == 0:  # 下载单个 MOD
            mod_url = self.single_mod_input.text().strip()
            if not mod_url:
                QMessageBox.warning(self, tr("error"), tr("请输入 MOD 的 URL。"))
                return
            mod_urls = [mod_url]
        else:  # 下载多个 MOD
            mod_urls_input = self.multi_mod_input.toPlainText().strip()
            if not mod_urls_input:
                QMessageBox.warning(self, tr("error"), tr("请输入 MOD 的 URL。"))
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
        self.thread.stopped_signal.connect(self.cleanup_after_thread)
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

    def update_ui(self, index):
        # 记录当前输入内容
        if index == 0:  # 下载单个 MOD
            if self.multi_mod_input.isVisible():
                self.single_mod_input.setText(self.multi_mod_input.toPlainText().splitlines()[0] if self.multi_mod_input.toPlainText() else '')
        elif index == 1:  # 下载多个 MOD
            if self.single_mod_input.isVisible():
                self.multi_mod_input.setPlainText(self.single_mod_input.text())

        if index == 2:  # 从文件读取 MOD 列表
            self.input_label.setVisible(False)
            self.single_mod_input.setVisible(False)
            self.multi_mod_input.setVisible(False)
            self.file_button.setVisible(True)
        else:
            self.input_label.setVisible(True)
            self.file_button.setVisible(False)
            if index == 0:
                self.input_label.setText(tr("enter_mod_url"))
                self.single_mod_input.setVisible(True)
                self.multi_mod_input.setVisible(False)
            elif index == 1:
                self.input_label.setText(tr("enter_mod_urls"))
                self.single_mod_input.setVisible(False)
                self.multi_mod_input.setVisible(True)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_log(self, message):
        self.log_text.append(message)

    def update_steamcmd_output(self, message):
        self.dynamic_output_label.setText(message)

    def download_finished(self):
        QMessageBox.information(self, tr("info"), tr("setup_complete"))
        self.enable_inputs()

    def prompt_for_app_info(self, mod_id, message, response):
        """
        弹出对话框，提示用户输入 AppID 和 MOD 名称
        """
        app_id, ok1 = QInputDialog.getText(self, tr("prompt"), tr("enter_app_id"))
        if not ok1 or not app_id.strip():
            response['cancelled'] = True
            return
        mod_name, ok2 = QInputDialog.getText(self, tr("prompt"), tr("enter_mod_name"))
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
                self, tr("prompt"), tr("exit_confirmation"),
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

if __name__ == "__main__":
    load_settings()      # 加载设置
    load_translations()  # 加载语言文件
    app = QApplication(sys.argv)
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        # 将异常信息写入日志文件
        with open('error.log', 'w', encoding='utf-8') as f:
            f.write(tr("exception_occurred") + ":\n")
            traceback.print_exc(file=f)
        sys.exit(1)
