"""Sejong Moodle login/player parsing, adapted from chuseok22-home-server's flow."""
import http.cookiejar
import json
import re
import ssl
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

SCHOOL = "https://ecampus.sejong.ac.kr"

class UserError(Exception):
    pass


def lecture_id(url: str) -> str:
    parsed = urlsplit(url)
    values = parse_qs(parsed.query).get("id", [])
    if (parsed.scheme != "https" or parsed.netloc != "ecampus.sejong.ac.kr"
            or parsed.path != "/mod/vod/viewer.php" or len(values) != 1
            or not re.fullmatch(r"[0-9]{1,12}", values[0])):
        raise UserError("세종대 강의 재생 주소(viewer.php?id=숫자)를 입력해 주세요.")
    return values[0]


def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", value).strip(" .")
    value = value.encode("utf-8")[:120].decode("utf-8", errors="ignore")
    return value or "미분류"


class PlayerParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stream = None
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "title":
            self.in_title = True
        if tag == "video" and attrs.get("data-setup-lazy"):
            try:
                config = json.loads(attrs["data-setup-lazy"])
                sources = config.get("sources", {})
                if isinstance(sources, dict):
                    self.stream = sources.get("src")
            except (ValueError, AttributeError):
                pass

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def extract_stream(html: str) -> tuple[str, str]:
    parser = PlayerParser()
    parser.feed(html)
    stream = parser.stream
    if not stream:
        match = re.search(r'https://[^\s"\'<>]+index\.m3u8', html)
        stream = match.group(0) if match else None
    if not isinstance(stream, str):
        raise UserError("영상 주소를 찾지 못했습니다. 강의 접근 권한이나 학교 플레이어 변경을 확인해 주세요.")
    parsed = urlsplit(stream)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or not parsed.path.endswith(".m3u8")
            or any(char in stream for char in "\r\n")):
        raise UserError("학교 페이지의 영상 주소 형식을 확인할 수 없습니다.")
    return stream, parser.title.strip()


class SchoolRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials and cookies must stay at the explicitly selected school.
        if urlsplit(newurl).netloc != "ecampus.sejong.ac.kr" or not newurl.startswith("https://"):
            raise UserError("학교 로그인 주소가 변경되었습니다. 외부 주소로 로그인을 전달하지 않았습니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SchoolSession:
    def __init__(self):
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()), SchoolRedirects())

    def page(self, path: str, form: dict | None = None) -> tuple[str, str]:
        data = urlencode(form).encode() if form else None
        request = Request(SCHOOL + path, data=data, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"})
        try:
            with self.opener.open(request, timeout=25) as response:
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise UserError("학교 페이지 응답이 너무 큽니다.")
                return response.url, body.decode("utf-8", errors="replace")
        except HTTPError as error:
            raise UserError(f"학교 사이트가 HTTP {error.code} 오류를 반환했습니다.") from None
        except (URLError, TimeoutError, ssl.SSLError):
            raise UserError("학교 사이트에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요. 계속 실패하면 운영자에게 알려 주세요.") from None

    def login(self, student_id: str, password: str):
        url, html = self.page("/login/index.php", {
            "ssoGubun": "Login", "type": "popup_login", "username": student_id,
            "password": password, "loginbutton": "로그인",
        })
        if urlsplit(url).path in {"/login/index.php", "/login.php"} or "logout.php" not in html:
            raise UserError("학교 로그인이 확인되지 않았습니다. 학번·비밀번호를 확인하거나 학교 사이트에서 직접 로그인해 주세요.")

    def stream(self, identifier: str):
        url, html = self.page("/mod/vod/viewer.php?" + urlencode({"id": identifier}))
        if urlsplit(url).path in {"/login/index.php", "/login.php"}:
            raise UserError("학교 로그인이 만료되었습니다. 다시 로그인한 뒤 재시도해 주세요.")
        return extract_stream(html)
