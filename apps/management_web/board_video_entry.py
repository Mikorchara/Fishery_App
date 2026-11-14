"""Opt-in Web startup for the board RTSP preview."""

import argparse

from .__main__ import main as web_main
from .app import board_video_for_startup
from .board_video import BoardVideo


def main(argv=None):
    parser = argparse.ArgumentParser(description='Management Web with board RTSP preview', allow_abbrev=False)
    parser.add_argument('--board-video', required=True)
    parser.add_argument('--simulation-mode', choices=('water-only',), required=True)
    parser.add_argument('--demo-video', help=argparse.SUPPRESS)
    parser.add_argument('--legacy-demo', action='store_true', help=argparse.SUPPRESS)
    args, web_args = parser.parse_known_args(argv)
    if args.demo_video is not None or args.legacy_demo:
        parser.error('BOARD_VIDEO_REQUIRES_DEVICE_MODE_WITHOUT_DEMO')
    try:
        video = BoardVideo(args.board_video)
    except ValueError as error:
        parser.error(str(error))

    # The factory runs in this context. Requests use the video it binds to the app.
    token = board_video_for_startup.set(video)
    try:
        return web_main([*web_args, '--simulation-mode', args.simulation_mode])
    finally:
        board_video_for_startup.reset(token)
        video.close()


if __name__ == '__main__':
    main()
