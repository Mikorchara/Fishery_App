"""Read one explicitly configured RTSP source into a local browser preview."""

from ipaddress import ip_address, ip_network
from queue import Empty, Full, Queue
import re
import shutil
import subprocess
from threading import Condition, Event, Lock, Thread

from flask import Response, jsonify, request


URL = '/media/board-video.mjpg'
BOUNDARY = b'fisheryframe'
FRAME_TIMEOUT = 8
MAX_JPEG_BYTES = 2 * 1024 * 1024
PRIVATE_NETWORKS = tuple(map(ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
RTSP_URL = re.compile(r'rtsp://([0-9.]{7,15})(?::([0-9]{1,5}))?((?:/[A-Za-z0-9_-][A-Za-z0-9._-]{0,127})+)')


def validate_board_video_url(source):
    match = RTSP_URL.fullmatch(source) if isinstance(source, str) and len(source) <= 256 else None
    try:
        if match:
            host = ip_address(match[1])
            port = int(match[2]) if match[2] is not None else 554
            if (host.is_loopback or any(host in network for network in PRIVATE_NETWORKS)) and 1 <= port <= 65535:
                return source
    except ValueError:
        pass
    raise ValueError('BOARD_VIDEO_RTSP_URL_INVALID')


def _read_frame(stream):
    if stream.readline(64) != b'--' + BOUNDARY + b'\r\n':
        return None
    if stream.readline(64).lower() != b'content-type: image/jpeg\r\n':
        return None
    size_line = re.fullmatch(rb'content-length: ([0-9]{1,7})\r\n', stream.readline(64).lower())
    if size_line is None or stream.readline(4) != b'\r\n':
        return None
    size = int(size_line[1])
    if not 4 <= size <= MAX_JPEG_BYTES:
        return None
    frame = stream.read(size)
    if len(frame) != size or not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
        return None
    if stream.read(2) != b'\r\n':
        return None
    return frame


class _MjpegStream:
    def __init__(self, process):
        self.process = process
        self.frames = Queue(maxsize=2)
        self.stopped = Event()
        self.close_lock = Lock()
        self.reader = Thread(target=self._read, name='board-video-reader', daemon=True)
        self.reader.start()

    def _offer(self, frame):
        while not self.stopped.is_set():
            try:
                self.frames.put(frame, timeout=.1)
                return
            except Full:
                continue

    def _read(self):
        try:
            with self.process.stdout as stream:
                while not self.stopped.is_set():
                    frame = _read_frame(stream)
                    if frame is None:
                        break
                    self._offer(frame)
        except (OSError, ValueError):
            pass
        finally:
            self._offer(None)

    def next_frame(self):
        if not self.stopped.is_set():
            try:
                return self.frames.get(timeout=FRAME_TIMEOUT)
            except Empty:
                return None
        return None

    def close(self):
        with self.close_lock:
            if self.stopped.is_set():
                return
            self.stopped.set()
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.reader.join(timeout=1)


class BoardVideo:
    """Open FFmpeg only while one local browser has requested the preview."""

    def __init__(self, source):
        self.source = validate_board_video_url(source)
        self.executable = shutil.which('ffmpeg')
        if self.executable is None:
            raise ValueError('BOARD_VIDEO_FFMPEG_REQUIRED')
        self._slot = Condition()
        self._active = None
        self._closed = False

    @staticmethod
    def metadata():
        return dict(kind='board_stream', source_kind='DEVICE_RTSP', label='开发板视频', url=URL)

    def open(self):
        with self._slot:
            self._slot.wait_for(lambda: self._active is None or self._closed, timeout=2)
            if self._active is not None or self._closed:
                return None
            command = [
                self.executable, '-nostdin', '-v', 'error', '-protocol_whitelist', 'tcp',
                '-f', 'rtsp', '-rtsp_transport', 'tcp', '-timeout', '5000000', '-i', self.source,
                '-map', '0:v:0', '-an', '-sn', '-dn', '-filter_threads', '1',
                '-vf', r'fps=6,scale=min(960\,iw):-2',
                '-c:v', 'mjpeg', '-threads', '1', '-q:v', '5', '-f', 'mpjpeg',
                '-boundary_tag', BOUNDARY.decode('ascii'), '-flush_packets', '1', 'pipe:1',
            ]
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._active = _MjpegStream(process)
            return self._active

    def release(self, stream):
        try:
            stream.close()
        finally:
            with self._slot:
                if self._active is stream:
                    self._active = None
                    self._slot.notify_all()

    def close(self):
        with self._slot:
            self._closed = True
            stream = self._active
            self._slot.notify_all()
        if stream is not None:
            self.release(stream)


def register_board_video(app, video):
    if type(video) is not BoardVideo:
        raise ValueError('INVALID_BOARD_VIDEO')

    @app.get(URL)
    def board_video():
        try:
            local = ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local = False
        if not local or request.headers.get('Sec-Fetch-Site') not in (None, 'none', 'same-origin'):
            return jsonify(error_code='BOARD_VIDEO_ACCESS_DENIED'), 403
        if request.method == 'HEAD':
            return Response(status=204)
        try:
            stream = video.open()
        except OSError:
            return jsonify(error_code='BOARD_VIDEO_UNAVAILABLE'), 503
        if stream is None:
            return jsonify(error_code='BOARD_VIDEO_BUSY'), 503
        first = stream.next_frame()
        if first is None:
            video.release(stream)
            return jsonify(error_code='BOARD_VIDEO_UNAVAILABLE'), 503

        def frames():
            frame = first
            try:
                while frame is not None:
                    header = (b'--' + BOUNDARY + b'\r\nContent-Type: image/jpeg\r\nContent-Length: '
                              + str(len(frame)).encode('ascii') + b'\r\n\r\n')
                    yield header + frame + b'\r\n'
                    frame = stream.next_frame()
            finally:
                video.release(stream)

        response = Response(frames(), content_type='multipart/x-mixed-replace; boundary=fisheryframe')
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.call_on_close(lambda: video.release(stream))
        return response
