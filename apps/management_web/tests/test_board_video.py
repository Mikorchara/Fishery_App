from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

from apps.management_web.app import create_app
from apps.management_web.board_video import BoardVideo, URL, _read_frame, validate_board_video_url
from apps.management_web.board_video_entry import main as board_video_main


JPEG = b'\xff\xd8image\xff\xd9'


class BoardVideoTests(TestCase):
    def test_board_entry_binds_preview_only_to_its_web_app_and_closes_on_exit(self):
        source = 'rtsp://127.0.0.1:8554/other.264'

        def start_web(args):
            self.assertEqual(args, ['--port', '8767', '--simulation-mode', 'water-only'])
            app = create_app(simulation_mode='water-only')
            self.assertEqual(app.test_client().get('/api/bootstrap').json['video_preview']['url'], URL)
            raise RuntimeError('forced stop')

        with patch('apps.management_web.board_video.shutil.which', return_value='ffmpeg'), \
             patch('apps.management_web.board_video_entry.web_main', side_effect=start_web), \
             patch.object(BoardVideo, 'close') as close:
            with self.assertRaisesRegex(RuntimeError, 'forced stop'):
                board_video_main(['--port', '8767', '--board-video', source, '--simulation-mode', 'water-only'])
            close.assert_called_once_with()

        legacy = create_app(simulation_mode='water-only').test_client()
        self.assertNotIn('video_preview', legacy.get('/api/bootstrap').json)
        self.assertEqual(legacy.get(URL).status_code, 404)

    def test_source_is_explicit_and_limited_to_local_networks(self):
        source = 'rtsp://192.168.68.178:554/normal.264'
        self.assertEqual(validate_board_video_url(source), source)
        for invalid in (
            'rtsp://8.8.8.8/normal.264', 'rtsp://localhost/normal.264',
            'rtsp://user:pass@127.0.0.1/normal.264', 'rtsp://127.0.0.1/normal.264?token=1',
            'rtsp://127.0.0.1/../normal.264', 'rtsp://127.0.0.1:65536/normal.264',
            'file:///normal.264',
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'BOARD_VIDEO_RTSP_URL_INVALID'):
                validate_board_video_url(invalid)

    def test_stream_uses_fixed_local_url_and_releases_the_reader_on_disconnect(self):
        source = 'rtsp://192.168.68.178:554/normal.264'
        with patch('apps.management_web.board_video.shutil.which', return_value='ffmpeg'):
            video = BoardVideo(source)
        app = create_app(simulation_mode='water-only', board_video=video)
        client = app.test_client()
        metadata = client.get('/api/bootstrap').json['video_preview']
        self.assertEqual(metadata['url'], URL)
        self.assertNotIn(source, str(metadata))
        with patch.object(video, 'open') as open_stream, patch.object(video, 'release') as release:
            open_stream.return_value.next_frame.return_value = JPEG
            self.assertEqual(client.get(URL, headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
            self.assertEqual(client.get(URL, environ_overrides={'REMOTE_ADDR': '192.168.68.178'}).status_code, 403)
            self.assertEqual(client.head(URL).status_code, 204)
            open_stream.assert_not_called()
            response = client.get(URL, buffered=False)
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Cross-Origin-Resource-Policy'], 'same-origin')
                self.assertTrue(next(iter(response.response)).endswith(JPEG + b'\r\n'))
            finally:
                response.close()
            release.assert_called_with(open_stream.return_value)

    def test_missing_first_frame_reports_unavailable(self):
        with patch('apps.management_web.board_video.shutil.which', return_value='ffmpeg'):
            video = BoardVideo('rtsp://127.0.0.1/normal.264')
        client = create_app(simulation_mode='water-only', board_video=video).test_client()
        with patch.object(video, 'open') as open_stream, patch.object(video, 'release') as release:
            open_stream.return_value.next_frame.return_value = None
            response = client.get(URL)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json['error_code'], 'BOARD_VIDEO_UNAVAILABLE')
            release.assert_called_once_with(open_stream.return_value)

    def test_frame_parser_checks_ffmpeg_multipart_headers_and_jpeg_size(self):
        data = b'--fisheryframe\r\nContent-type: image/jpeg\r\nContent-length: 9\r\n\r\n' + JPEG + b'\r\n'
        self.assertEqual(_read_frame(BytesIO(data)), JPEG)
        self.assertIsNone(_read_frame(BytesIO(data.replace(b'length: 9', b'length: 2097153'))))
        self.assertIsNone(_read_frame(BytesIO(data[:-4])))
