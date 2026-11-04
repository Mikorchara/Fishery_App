"""Shared optional mode menu; never starts a listener or creates a report store."""
from apps.device_reports.binding import validate_binding


def select_mode(args):
    if args.interactive_mode and not getattr(args, 'check', False):
        while True:
            print('运行模式：1. 完整模拟（默认）  2. 设备联调（仅模拟水质）  0. 退出')
            choice = input('选择模式 [1/2/0]：').strip() or '1'
            if choice == '0':
                return False
            if choice in ('1', '2'):
                args.simulation_mode = 'water-only' if choice == '2' else 'full'
                break
    validate_binding(args.simulation_mode, args.device_report_directory, args.device_report_device_id)
    if args.simulation_mode == 'water-only' and not args.device_report_directory:
        print('仅模拟水质；尚未绑定设备报告。真实接入请指定报告目录与设备ID，并单独启动接收器。')
    return True
