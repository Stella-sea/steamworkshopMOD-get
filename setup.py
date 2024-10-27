# setup.py

import os
import sys
import subprocess
import re
import platform

SETUP_COMPLETE_FILE = '.setup_complete'

def check_setup_complete():
    return os.path.exists(SETUP_COMPLETE_FILE)

def record_setup_complete():
    with open(SETUP_COMPLETE_FILE, 'w') as f:
        f.write('Setup complete')

def find_python310():
    """
    尝试查找 Python 3.10 及以上版本的可执行文件
    """
    possible_names = ['python3.10', 'python3', 'python']
    if platform.system() == 'Windows':
        possible_names.extend(['py -3.10', 'py -3'])
    for name in possible_names:
        try:
            if ' ' in name:
                command = name.split()
            else:
                command = [name]
            command.append('--version')
            output = subprocess.check_output(command, stderr=subprocess.STDOUT)
            version_str = output.decode()
            version_match = re.search(r'Python\s+(\d+)\.(\d+)\.(\d+)', version_str)
            if version_match:
                major, minor, patch = map(int, version_match.groups())
                if major == 3 and minor >= 10:
                    return command[0]
        except Exception:
            continue
    return None

def download_and_install_python():
    """
    提示用户安装 Python 3.10+
    """
    print('需要 Python 3.10 或更高版本，请先安装后再运行此脚本。')
    input('按回车键退出...')
    sys.exit(1)

def parse_requirements_from_main():
    """
    从 main.py 中解析导入的第三方库
    """
    requirements = set()
    with open('main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    # 查找所有的 import 语句
    import_statements = re.findall(r'^\s*(?:import|from)\s+([^\s]+)', content, re.MULTILINE)
    for statement in import_statements:
        module = statement.split('.')[0]
        if module not in sys.builtin_module_names and module not in standard_lib_modules:
            requirements.add(module)
    return list(requirements)

# 常见的标准库模块列表
standard_lib_modules = {
    'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio', 'asyncore', 'atexit',
    'audioop', 'base64', 'binascii', 'binhex', 'bisect', 'builtins', 'bz2', 'calendar', 'cgi',
    'cgitb', 'chunk', 'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections', 'colorsys',
    'compileall', 'concurrent', 'configparser', 'contextlib', 'copy', 'copyreg', 'crypt', 'csv',
    'ctypes', 'curses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis', 'doctest', 'dummy_threading',
    'email', 'encodings', 'enum', 'errno', 'faulthandler', 'fcntl', 'filecmp', 'fileinput',
    'fnmatch', 'fractions', 'functools', 'gc', 'getopt', 'getpass', 'gettext', 'glob', 'grp',
    'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http', 'imaplib', 'imghdr', 'imp', 'importlib',
    'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword', 'linecache', 'locale', 'logging',
    'lzma', 'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder', 'msilib',
    'multiprocessing', 'netrc', 'nntplib', 'numbers', 'operator', 'optparse', 'os', 'parser',
    'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil', 'platform', 'plistlib', 'poplib',
    'posix', 'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc',
    'queue', 'quopri', 'random', 're', 'readline', 'reprlib', 'resource', 'rlcompleter',
    'runpy', 'sched', 'select', 'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site',
    'smtpd', 'smtplib', 'socket', 'socketserver', 'spwd', 'sqlite3', 'ssl', 'stat', 'statistics',
    'string', 'stringprep', 'struct', 'subprocess', 'sunau', 'symbol', 'symtable', 'sys',
    'sysconfig', 'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios', 'textwrap', 'threading',
    'time', 'timeit', 'tkinter', 'token', 'tokenize', 'trace', 'traceback', 'tracemalloc',
    'tty', 'turtle', 'types', 'unicodedata', 'unittest', 'urllib', 'uuid', 'venv', 'warnings',
    'wave', 'weakref', 'webbrowser', 'wsgiref', 'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile',
    'zipimport', 'zlib'
}

def create_virtualenv(python_executable):
    """
    使用指定的 Python 可执行文件创建虚拟环境
    """
    venv_dir = '.venv'
    if not os.path.exists(venv_dir):
        subprocess.check_call([python_executable, '-m', 'venv', venv_dir])
    return get_venv_python()

def get_venv_python():
    """
    获取虚拟环境中 Python 可执行文件的路径
    """
    venv_dir = '.venv'
    if platform.system() == 'Windows':
        python_executable = 'python.exe'
        python_path = os.path.join(venv_dir, 'Scripts', python_executable)
    else:
        python_executable = 'python'
        python_path = os.path.join(venv_dir, 'bin', python_executable)
    return python_path

def print_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """
    打印进度条到控制台。

    参数:
    - iteration: 当前的迭代次数 (int)
    - total: 总的迭代次数 (int)
    - prefix: 前缀字符串 (str)
    - suffix: 后缀字符串 (str)
    - length: 进度条的长度 (int)
    - fill: 进度条的填充字符 (str)
    """
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end='\r')
    # 当进度达到总量时，打印新行
    if iteration == total:
        print()


def install_requirements(venv_python, requirements):
    """
    在虚拟环境中安装所需的库
    """
    if not requirements:
        return
    # 升级 pip
    print('正在升级 pip...')
    try:
        subprocess.check_call([venv_python, '-m', 'pip', 'install', '--upgrade', 'pip', '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'])
    except subprocess.CalledProcessError:
        print('无法通过清华源升级 pip，尝试使用官方源...')
        subprocess.check_call([venv_python, '-m', 'pip', 'install', '--upgrade', 'pip'])
    # 安装依赖
    print('正在安装依赖库...')
    total = len(requirements)
    for i, req in enumerate(requirements, start=1):
        print_progress_bar(i - 1, total, prefix='安装进度:', suffix='完成', length=50)
        try:
            subprocess.check_call([venv_python, '-m', 'pip', 'install', req, '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'])
        except subprocess.CalledProcessError:
            print(f'无法通过清华源安装 {req}，尝试使用官方源...')
            subprocess.check_call([venv_python, '-m', 'pip', 'install', req])
    print_progress_bar(total, total, prefix='安装进度:', suffix='完成', length=50)

def run_main(venv_python):
    """
    使用虚拟环境中的 Python 运行 main.py，并捕获输出
    """
    result = subprocess.run([venv_python, 'main.py'], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"运行 main.py 时出错，退出代码：{result.returncode}")
        print("标准输出：")
        print(result.stdout)
        print("错误输出：")
        print(result.stderr)
        sys.exit(result.returncode)

def main():
    if check_setup_complete():
        # 已完成设置，直接运行 main.py
        venv_python = get_venv_python()
        if not os.path.exists(venv_python):
            print('未找到虚拟环境。请删除 .setup_complete 文件并重新运行此脚本。')
            sys.exit(1)
        run_main(venv_python)
        return

    # 检查 Python 版本
    python_executable = find_python310()
    if python_executable is None:
        download_and_install_python()
        sys.exit(1)
    else:
        print(f'使用的 Python 可执行文件: {python_executable}')

    # 解析 main.py 中的依赖
    requirements = parse_requirements_from_main()
    print('检测到的依赖库:', requirements)

    # 创建虚拟环境
    venv_python = create_virtualenv(python_executable)
    print('虚拟环境已创建。')

    # 安装依赖
    install_requirements(venv_python, requirements)
    print('依赖库已安装。')

    # 记录设置完成
    record_setup_complete()
    print('设置完成。')

    # 运行 main.py
    run_main(venv_python)

if __name__ == '__main__':
    main()