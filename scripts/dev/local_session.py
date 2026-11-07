"""Existing Web/Simulator launcher, with optional visible Windows demo consoles."""
import argparse
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
# Script execution with -I must bind imports to this project, not another checkout.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Deliberately limited to user-facing demos; fault-injection scenarios
# remain available only through the original Simulator CLI.
DEMO_SCENARIOS = (
    ('normal', '正常水质'), ('low_oxygen', '低溶解氧'),
    ('suspected_disease', '疑似疾病'), ('reduced_feeding', '摄食减少'),
    ('combined_anomaly', '复合异常'), ('device_offline', '设备离线'),
    ('oxygen_drop_recovery', '溶解氧快速下降后逐步回升'),
    ('device_visual_recovery', '模拟开发板视觉信号（异常后消退）'),
)


def choose_scenario(*, read=input, emit=print, water_only=False):
    choices = dict(zip(('1', '2', '3', '4', '5', '6', '7', '9'), DEMO_SCENARIOS))
    if water_only:
        del choices['9']
    available = '1–7' if water_only else '1–7、9'
    emit('请选择模拟场景（开始发送数据前选择）：')
    for number, (key, label) in choices.items():
        emit(f'  {number}. {label} ({key})')
    emit('  0. 退出（8 也可退出）')
    while True:
        try:
            value = read(f'输入 {available}，Enter 默认正常水质，0 退出：').strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if value in ('0', '8'):
            return None
        if value == '':
            return choices['1']
        if value in choices:
            return choices[value]
        emit(f'输入无效，请输入 {available} 或 0。直接 Enter 选择正常水质。')


def require_free_port(port):
    # No discovery/termination of the process occupying the port.
    with socket.socket() as connection:
        connection.settimeout(.3)
        if connection.connect_ex(('127.0.0.1',port)) == 0:
            raise RuntimeError('LOCAL_PORT_IN_USE')
    with socket.socket() as probe:
        # Allow a just-stopped server's TIME_WAIT, after rejecting live listeners.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1',port))
        except OSError:
            raise RuntimeError('LOCAL_PORT_IN_USE') from None


def commands(python, scenario, port, seed, *, assistant=True, streaming=True, multi_round=True, history=True,
             data_root=None, user_data=False, demo_video=None, score_trial=False, simulation_mode='full',device_report_directory=None,device_report_device_id=None):
    from apps.device_reports.binding import validate_binding
    validate_binding(simulation_mode,device_report_directory,device_report_device_id)
    if score_trial and not assistant:raise RuntimeError('SCORE_TRIAL_REQUIRES_ASSISTANT')
    server = [python,'-m','apps.management_web','--port',str(port),'--enable-ingestion']
    if data_root is not None:
        server += ['--data-root',str(data_root)]
    if user_data:
        server += ['--user-data']
    if demo_video is not None:server+=['--demo-video',str(Path(demo_video).absolute())]
    if simulation_mode!='full':server+=['--simulation-mode',simulation_mode]
    if device_report_directory is not None:server+=['--device-report-directory',str(Path(device_report_directory).absolute()),'--device-report-device-id',device_report_device_id]
    if assistant:
        server += ['--enable-assistant']
        server += [flag for enabled,flag in ((multi_round,'--assistant-multi-round-trial'),
            (streaming,'--assistant-streaming-trial'),(history,'--assistant-history-trial')) if enabled]
        if history and (multi_round or streaming):server += ['--assistant-tools-trial']
        if score_trial:server+=['--assistant-score-trial']
    return (server,[python,'-m','apps.simulator','--scenario',scenario,'--server',f'http://127.0.0.1:{port}',
                    '--seed',str(seed),'--interval','10',*(['--mode',simulation_mode] if simulation_mode!='full' else [])])


def ready(port):
    connection = HTTPConnection('127.0.0.1',port,timeout=.5)
    try:
        connection.request('GET','/api/bootstrap')
        response = connection.getresponse()
        return response.status == 200 and isinstance(json.load(response),dict)
    except (OSError,ValueError):
        return False
    finally:
        connection.close()


def run_local(scenario='normal', port=8766, seed=42, *, root=ROOT, python=None,
              assistant=True, streaming=True, multi_round=True, history=True,
              data_root=None, user_data=False, show_terminals=False, open_browser=False, interactive_scenario=False,
              launch=subprocess.Popen, is_ready=ready, sleep=time.sleep, emit=print,
              browse=webbrowser.open, demo_video=None, score_trial=False, simulation_mode='full',device_report_directory=None,device_report_device_id=None):
    if interactive_scenario and not show_terminals:
        raise RuntimeError('LOCAL_SCENARIO_MENU_REQUIRES_TERMINALS')
    require_free_port(port)
    child_env = os.environ.copy()
    # Installed/source management startup must not inherit an old repository path.
    child_env.pop('PYTHONPATH', None)
    child_env.pop('PYTHONHOME', None)
    child_env['FISHERY_SIM_INGEST_TOKEN'] = secrets.token_hex(32)
    children = []
    try:
        server,simulator = commands(python or sys.executable,scenario,port,seed,
            assistant=assistant,streaming=streaming,multi_round=multi_round,history=history,
            data_root=data_root,user_data=user_data,demo_video=demo_video,score_trial=score_trial,simulation_mode=simulation_mode,device_report_directory=device_report_directory,device_report_device_id=device_report_device_id)
        options = dict(cwd=root,env=child_env)
        if show_terminals:
            if os.name != 'nt':
                raise RuntimeError('LOCAL_WINDOWS_REQUIRED')
            options['creationflags'] = subprocess.CREATE_NEW_CONSOLE
            # Same modules/flags, wrapped only to label the two visible consoles.
            def visible(command, role):
                return [command[0], '-I', '-B', '-u', str(Path(__file__).resolve()),
                        '--console-role', role,
                        *(['--interactive-scenario'] if role == 'simulator' and interactive_scenario else []),
                        '--', *command[1:]]
            server, simulator = visible(server, 'web'), visible(simulator, 'simulator')
        else:
            if os.name == 'nt':
                options['creationflags'] = subprocess.CREATE_NO_WINDOW
            options.update(stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        children.append(launch(server,**options))
        deadline = time.monotonic()+20
        while not is_ready(port):
            if children[0].poll() is not None:
                raise RuntimeError('LOCAL_SERVER_START_FAILED')
            if time.monotonic() >= deadline:
                raise RuntimeError('LOCAL_SERVER_START_TIMEOUT')
            sleep(.1)
        if children[0].poll() is not None:
            raise RuntimeError('LOCAL_SERVER_START_FAILED')
        children.append(launch(simulator,**options))
        scene = '请在 Simulator 窗口选择场景；选择前不上报' if interactive_scenario else f'场景 {scenario} · 每10秒上报'
        emit(f'本机服务 http://127.0.0.1:{port} · {scene}。Ctrl+C 停止两进程。')
        emit('Qwen三工具本地实验按启动参数启用；Tool仍须用户授权。启动不调用模型。')
        if open_browser:
            try:
                if not browse(f'http://127.0.0.1:{port}'):
                    emit('浏览器未自动打开，请使用以上地址。')
            except OSError:
                emit('浏览器未自动打开，请使用以上地址。')
        while all(child.poll() is None for child in children):
            sleep(.2)
        if show_terminals and any(child.poll() in (0, 0xC000013A) for child in children):
            return 0  # Ctrl+C / closing either owned console stops the whole session.
        raise RuntimeError('LOCAL_CHILD_EXITED')
    except KeyboardInterrupt:
        emit('正在停止本次启动的服务器和模拟器。')
        return 0
    finally:
        # Only Popen objects created here are owned. Leave every other process alone.
        for child in reversed(children):
            if child.poll() is None:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
        for child in reversed(children):
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)
        child_env.pop('FISHERY_SIM_INGEST_TOKEN',None)


def console_role(argv):
    import ctypes
    import runpy
    role, *remaining = argv
    interactive = remaining[:1] == ['--interactive-scenario']
    if interactive:
        remaining = remaining[1:]
    separator, *arguments = remaining
    if role not in ('web', 'simulator') or interactive and role != 'simulator':
        raise RuntimeError('INVALID_LOCAL_CONSOLE')
    if separator != '--' or arguments[:1] != ['-m'] or arguments[1:2] != [
            'apps.management_web' if role == 'web' else 'apps.simulator']:
        raise RuntimeError('INVALID_LOCAL_CONSOLE')
    port = arguments[arguments.index('--port')+1] if role == 'web' else arguments[arguments.index('--server')+1].rsplit(':',1)[1]
    ctypes.windll.kernel32.SetConsoleTitleW('AI 监测系统 · '+('Web' if role == 'web' else 'Simulator')+' · '+port)
    water_only = role == 'simulator' and '--mode' in arguments and arguments[arguments.index('--mode')+1] == 'water-only'
    print('AI 监测系统 · '+('Web 服务' if role == 'web' else '模拟器（每10秒更新水质）' if water_only else '模拟器（每10秒更新水质与视觉数据）'), flush=True)
    if water_only:
        print('设备联调：仅模拟水质。开发板视觉报告由独立接收器提供。', flush=True)
    print('按 Ctrl+C 或关闭任一窗口，停止本次启动的两个服务。', flush=True)
    try:
        if interactive:
            choice = choose_scenario(water_only=water_only)
            if choice is None:
                print('已取消模拟；正在停止本次 Web / Simulator。', flush=True)
                return 0
            scenario, label = choice
            arguments[arguments.index('--scenario')+1] = scenario
            print(f'当前场景：{label} ({scenario})', flush=True)
            print('模拟上报状态：已启动；首个完整窗口约10秒，之后每10秒上报。', flush=True)
            print('下方 window 状态为实际发送结果；device offline / no report 表示未发送。', flush=True)
        sys.argv = [arguments[1], *arguments[2:]]
        runpy.run_module(arguments[1], run_name='__main__', alter_sys=True)
        return 0
    except KeyboardInterrupt:
        return 0


ERROR_HELP = {
    'LOCAL_PORT_IN_USE': '端口已占用。请先关闭原演示窗口；不会结束占用端口的外部程序。',
    'DEMO_KNOWLEDGE_EMPTY_REQUIRES_REVIEW': '已有演示知识库为空，已停止；请人工核对，不会覆盖或重建。',
    'DEMO_SOURCE_BUSY_CLOSE_FORMAL_WEB': '正式知识库正在使用或存在 SQLite 日志。请正常关闭正式 Web/编辑器后重试。',
    'DEMO_SOURCE_KNOWLEDGE_MISSING': '找不到正式知识库，未建立空白演示库。请核对当前 Windows 用户的数据目录。',
    'LOCAL_JOB_UNAVAILABLE': '无法启用 Windows 进程回收保护，未启动服务。',
}


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ['--console-role']:
        return console_role(arguments[1:])
    parser=argparse.ArgumentParser(description='本机管理服务+模拟器；不会发起模型请求')
    parser.add_argument('--scenario',choices=tuple(key for key, _ in DEMO_SCENARIOS),default='normal')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--seed',type=int,default=42)
    locations=parser.add_mutually_exclusive_group()
    locations.add_argument('--data-root',type=Path)
    locations.add_argument('--user-data',action='store_true')
    locations.add_argument('--demo',action='store_true',help='独立演示实例，首次只读复制正式知识库')
    parser.add_argument('--show-terminals',action='store_true')
    parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--interactive-scenario',action='store_true',help='在 Simulator 终端先选择场景；仅与 --show-terminals 使用')
    for name in ('assistant','streaming','multi-round','history'):
        parser.add_argument('--no-'+name,action='store_true')
    parser.add_argument('--demo-video',type=Path)
    parser.add_argument('--score-trial',action='store_true')
    parser.add_argument('--simulation-mode',choices=('full','water-only'),default='full')
    parser.add_argument('--interactive-mode',action='store_true')
    parser.add_argument('--auto-device-reports',action='store_true')
    parser.add_argument('--device-report-directory',type=Path)
    parser.add_argument('--device-report-device-id')
    args=parser.parse_args(arguments)
    from scripts.dev.device_mode import select_mode
    try:
        if not select_mode(args):return 0
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.port <= 65535:
        parser.error('INVALID_LOCAL_PORT')
    if args.interactive_scenario and not args.show_terminals:
        parser.error('LOCAL_SCENARIO_MENU_REQUIRES_TERMINALS')
    try:
        from contextlib import nullcontext
        from apps.management_web.instance import safe_path
        from apps.ai_backend.secure_files import exclusive_lock
        from apps.ai_backend.secure_files import SecureFileError
        from apps.knowledge.repository import KnowledgeError
        from apps.ai_backend.tools.policy import ToolPolicyError
        require_free_port(args.port)
        # Only the standalone CLI joins the job; its handle lives until this
        # supervisor exits. Forced termination therefore also removes descendants.
        if args.show_terminals:
            from scripts.dev.windows_job import own_process_tree
            own_process_tree()
        outputs = ROOT/'outputs'
        safe_path(outputs)
        outputs.mkdir(exist_ok=True)
        lock = exclusive_lock(outputs/('.local-session-'+str(args.port)+'.lock')) if args.show_terminals or args.demo else nullcontext()
        with lock:
            require_free_port(args.port)
            if args.demo:
                from scripts.dev.demo_instance import prepare_demo
                paths, created, count = prepare_demo(ROOT)
                args.data_root = paths.data_root
                print(f'演示实例：{"首次建立" if created else "复用"} · 知识 {count} 条 · {paths.data_root}',flush=True)
            return run_local(args.scenario,args.port,args.seed,assistant=not args.no_assistant,
                streaming=not args.no_streaming,multi_round=not args.no_multi_round,history=not args.no_history,
                data_root=args.data_root,user_data=args.user_data,show_terminals=args.show_terminals,
                open_browser=args.open_browser,interactive_scenario=args.interactive_scenario,
                demo_video=args.demo_video,score_trial=args.score_trial,simulation_mode=args.simulation_mode,device_report_directory=args.device_report_directory,device_report_device_id=args.device_report_device_id)
    except (RuntimeError, OSError, ValueError, SecureFileError, KnowledgeError, ToolPolicyError) as error:
        code = str(error) if isinstance(error, (RuntimeError, ValueError)) else getattr(error, 'code', 'LOCAL_STORAGE_OR_PERMISSION_ERROR')
        print(code+' · '+ERROR_HELP.get(code, '启动已停止。请保留现有数据，核对演示实例或手动运行以查看错误。'),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
