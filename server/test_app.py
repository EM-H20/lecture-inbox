"""Run with npm test. School authentication and CDN downloads are simulated."""
import asyncio
import html
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.app import DownloadResponse, Job, Session, Store, create_app, validate_cdn
from server.school import SchoolExpired, UserError, extract_stream, lecture_id, safe_name

# Synthetic HTML matching the selectors in the upstream course.py and its tests.
COURSES_HTML = '''<a href="/login/logout.php">로그아웃</a><table>
<tr><td>2026</td><td>2학기</td><td><span>교과</span>
<a class="coursefullname" href="https://ecampus.sejong.ac.kr/course/view.php?id=42">자료 &amp; <b>구조</b></a></td></tr>
<tr><td>2026</td><td>2학기</td><td><a class="coursefullname" href="/course/view.php?id=42">중복</a></td></tr>
<tr><td>2026</td><td>2학기</td><td><a class="coursefullname" href="https://evil.example/course/view.php?id=99">외부</a></td></tr>
</table>'''
LECTURES_HTML = '''<ul><li class="activity vod modtype_vod" id="module-123">
<a><span class="instancename">1주차 <b>소개</b><span class="accesshide"> 동영상</span></span></a></li>
<li class="activity label" id="module-456"><span class="instancename">공지</span></li>
<li class="activity vod" id="module-invalid"><span class="instancename">잘못된 ID</span></li></ul>'''


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), max_bytes=1024)
        self.client_context = TestClient(create_app(self.store))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, identifier="12345678"):
        with patch('server.app.SchoolSession.login'):
            response = self.client.post('/api/login', json={'studentId': identifier, 'password': 'test-only-password'})
        self.assertEqual(response.status_code, 200)
        token = response.json()['token']
        return token, {'Authorization': 'Bearer ' + token}

    def ready_job(self, token):
        session = self.store.sessions[token]
        job = Job(session.owner, '388827', '바리스타수업.mp4', status='ready', expires=time.time() + 60)
        self.store.jobs[job.id] = job
        folder = self.store.root / job.id
        folder.mkdir()
        (folder / 'video.mp4').write_bytes(b'test-video-bytes')
        return job

    def test_two_users_cannot_list_download_or_delete_each_others_files(self):
        token_a, headers_a = self.login()
        _, headers_b = self.login('87654321')
        job = self.ready_job(token_a)
        self.assertEqual(self.client.get('/api/jobs', headers=headers_b).json()['jobs'], [])
        self.assertEqual(self.client.post(f'/api/jobs/{job.id}/ticket', headers=headers_b).status_code, 404)
        self.assertEqual(self.client.delete(f'/api/jobs/{job.id}', headers=headers_b).status_code, 404)
        ticket = self.client.post(f'/api/jobs/{job.id}/ticket', headers=headers_a).json()['path']
        response = self.client.get(ticket)
        self.assertEqual(response.content, b'test-video-bytes')
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get(ticket).status_code, 410)
        self.assertEqual(job.transfers, 0)

    def test_logout_revokes_issued_ticket_and_removes_temporary_files(self):
        token, headers = self.login()
        job = self.ready_job(token)
        ticket = self.client.post(f'/api/jobs/{job.id}/ticket', headers=headers).json()['path']
        self.assertEqual(self.client.post('/api/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get(ticket).status_code, 410)
        self.assertFalse((self.store.root / job.id).exists())
        self.assertEqual(self.client.get('/api/jobs', headers=headers).status_code, 401)

    def test_file_in_use_survives_logout_until_response_closes(self):
        token, _ = self.login()
        job = self.ready_job(token)
        ticket = self.store.ticket(self.store.sessions[token], job.id)
        self.store.claim(ticket)
        self.store.logout(token)
        self.assertTrue((self.store.root / job.id / 'video.mp4').exists())
        async def send(message):
            pass
        async def receive():
            return {'type': 'http.request'}
        asyncio.run(DownloadResponse(self.store, job)({'type': 'http', 'method': 'GET', 'headers': []}, receive, send))
        self.assertFalse((self.store.root / job.id).exists())

    def test_expired_session_and_expired_file_are_rejected(self):
        token, headers = self.login()
        job = self.ready_job(token)
        job.expires = time.time() - 1
        self.assertEqual(self.client.post(f'/api/jobs/{job.id}/ticket', headers=headers).status_code, 409)
        self.store.collect()
        self.assertNotIn(job.id, self.store.jobs)
        self.store.sessions[token].expires = time.time() - 1
        self.assertEqual(self.client.get('/api/jobs', headers=headers).status_code, 401)

    def test_invalid_login_does_not_echo_password_and_rate_limit_is_bounded(self):
        response = self.client.post('/api/login', json={'studentId': 'invalid', 'password': 'private-secret'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('private-secret', response.text)
        for _ in range(5):
            self.store.login_limit('test-ip', 'student')
        with self.assertRaises(HTTPException) as raised:
            self.store.login_limit('test-ip', 'student')
        self.assertEqual(raised.exception.status_code, 429)

    def test_job_creation_limits_and_remote_url_validation(self):
        token, headers = self.login()
        bad = self.client.post('/api/jobs', headers=headers, json={'url': 'http://127.0.0.1/private'})
        self.assertEqual(bad.status_code, 400)
        with patch.object(self.store.executor, 'submit'):
            body = {'url': 'https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=388827', 'name': '../수업'}
            first = self.client.post('/api/jobs', headers=headers, json=body)
            second = self.client.post('/api/jobs', headers=headers, json=body)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        self.assertNotIn('/', first.json()['name'])

    def test_pipeline_retries_referer_without_publishing_partial_file(self):
        token, _ = self.login()
        session = self.store.sessions[token]
        job = Job(session.owner, '388827', '강의.mp4')
        self.store.jobs[job.id] = job
        calls = []
        def run(job, stream, path, referer=False):
            calls.append(referer)
            path.write_bytes(b'partial' if not referer else b'complete')
            return 'ok' if referer else '403'
        with patch.object(session.school, 'stream', return_value=('https://cdn.example.com/index.m3u8', '제목')), patch('server.app.validate_cdn'), patch.object(self.store, 'run_ffmpeg', side_effect=run):
            self.store.download(job, session.school)
        self.assertEqual(calls, [False, True])
        self.assertEqual(job.status, 'ready')
        self.assertEqual((self.store.root / job.id / 'video.mp4').read_bytes(), b'complete')
        self.assertFalse((self.store.root / job.id / 'video.part').exists())

    def test_failure_removes_partial_and_does_not_leak_signed_urls(self):
        token, _ = self.login()
        session = self.store.sessions[token]
        job = Job(session.owner, '388827', '강의.mp4')
        self.store.jobs[job.id] = job
        with patch.object(session.school, 'stream', side_effect=RuntimeError('https://cdn.example.com/SECRET/index.m3u8')):
            self.store.download(job, session.school)
        self.assertEqual(job.status, 'failed')
        self.assertNotIn('SECRET', job.error)
        self.assertFalse((self.store.root / job.id).exists())

    def test_cors_and_anonymous_requests(self):
        self.assertEqual(self.client.get('/api/jobs').status_code, 401)
        response = self.client.options('/api/login', headers={'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(response.status_code, 400)
        response = self.client.options('/api/login', headers={'Origin': 'http://localhost:4317', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:4317')

    def test_catalog_parsing_and_selected_lecture_download(self):
        token, headers = self.login()
        school = self.store.sessions[token].school
        with patch.object(school, 'page', return_value=('https://ecampus.sejong.ac.kr/local/ubion/user/index.php', COURSES_HTML)) as page:
            result = self.client.get('/api/courses?year=2026&semester=20', headers=headers)
            self.assertEqual(result.json(), {'courses': [{'id': '42', 'name': '자료 & 구조', 'year': '2026', 'semester': '2학기'}]})
            page.assert_called_once_with('/local/ubion/user/index.php?year=2026&semester=20')
        with patch.object(school, 'page', return_value=('https://ecampus.sejong.ac.kr/course/view.php?id=42', LECTURES_HTML)) as page:
            result = self.client.get('/api/courses/42/lectures', headers=headers)
            lectures = result.json()['lectures']
            self.assertEqual(lectures, [{'id': '123', 'title': '1주차 소개', 'url': 'https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=123'}])
            page.assert_called_once_with('/course/view.php?id=42')
        with patch.object(self.store.executor, 'submit'):
            result = self.client.post('/api/jobs', headers=headers, json={'url': lectures[0]['url'], 'name': lectures[0]['title']})
        self.assertEqual(result.status_code, 202)
        self.assertEqual(self.store.jobs[result.json()['id']].lecture_id, '123')

    def test_catalog_uses_each_users_session_and_validates_filters(self):
        token_a, headers_a = self.login()
        token_b, headers_b = self.login('87654321')
        for path in ('/api/courses', '/api/courses/42/lectures'):
            self.assertEqual(self.client.get(path).status_code, 401)
        with patch.object(self.store.sessions[token_a].school, 'courses', return_value=[{'id': '42'}]), patch.object(self.store.sessions[token_b].school, 'courses', return_value=[]):
            self.assertEqual(self.client.get('/api/courses', headers=headers_a).json()['courses'], [{'id': '42'}])
            self.assertEqual(self.client.get('/api/courses', headers=headers_b).json()['courses'], [])
        with patch.object(self.store.sessions[token_b].school, 'lectures', side_effect=UserError('학교 사이트가 HTTP 403 오류를 반환했습니다.')):
            self.assertEqual(self.client.get('/api/courses/42/lectures', headers=headers_b).status_code, 502)
        for path in ('/api/courses?year=abc', '/api/courses?semester=30', '/api/courses/not-an-id/lectures'):
            self.assertEqual(self.client.get(path, headers=headers_a).status_code, 422)

    def test_catalog_expiry_errors_and_late_logout_response(self):
        token, headers = self.login()
        school = self.store.sessions[token].school
        job = self.ready_job(token)
        with patch.object(school, 'page', return_value=('https://ecampus.sejong.ac.kr/local/ubion/user/index.php', '<table></table>')):
            response = self.client.get('/api/courses', headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertIn('만료', response.json()['detail'])
            self.assertIn(job.id, self.store.jobs)
        for login_path in ('/login.php', '/login/index.php'):
            with patch.object(school, 'page', return_value=('https://ecampus.sejong.ac.kr' + login_path, '')):
                with self.assertRaises(SchoolExpired):
                    school.lectures('42')
        with patch.object(school, 'page', return_value=('https://ecampus.sejong.ac.kr/local/ubion/user/index.php', '<a href="logout.php">나가기</a>')):
            self.assertEqual(school.courses(), [])
        def late_result(*args):
            self.store.logout(token)
            return [{'id': '42'}]
        with patch.object(school, 'courses', side_effect=late_result):
            self.assertEqual(self.client.get('/api/courses', headers=headers).status_code, 401)

    def test_player_parser_preserves_escaped_urls_and_rejects_local_urls(self):
        url = 'https://cdn.example.com/token/index.m3u8'
        config = json.dumps({'sources': {'src': url}}).replace('/', r'\/')
        source = '<title>강의</title><video data-setup-lazy="' + html.escape(config, quote=True) + '"></video>'
        self.assertEqual(extract_stream(source), (url, '강의'))
        self.assertEqual(lecture_id('https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=388827'), '388827')
        for value in ('file:///etc/passwd', 'https://ecampus.sejong.ac.kr.evil.com/mod/vod/viewer.php?id=1'):
            with self.assertRaises(UserError):
                lecture_id(value)
        self.assertLessEqual(len(safe_name('한' * 200).encode()), 120)
        with patch('server.app.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(UserError):
                validate_cdn('https://cdn.example.com/index.m3u8')


if __name__ == '__main__':
    unittest.main()
