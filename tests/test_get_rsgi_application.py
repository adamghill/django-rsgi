from django.core.signals import request_started
from django.db import close_old_connections
from django.test import SimpleTestCase, override_settings

from django_rsgi import get_rsgi_application

from .mocks import MockRSGIProtocol, MockRSGIScope


@override_settings(ROOT_URLCONF="tests.urls", ALLOWED_HOSTS=["*"])
class RSGITest(SimpleTestCase):
    def setUp(self):
        request_started.disconnect(close_old_connections)
        self.addCleanup(request_started.connect, close_old_connections)

    async def test_get_rsgi_application(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(path="/")
        protocol = MockRSGIProtocol()

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        self.assertEqual(protocol.response["body"], b"Hello World!")
        headers = dict(protocol.response["headers"])
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")

    async def test_rsgi_query_string(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(path="/", query_string="name=RSGI")
        protocol = MockRSGIProtocol()

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        self.assertEqual(protocol.response["body"], b"Hello RSGI!")

    async def test_rsgi_post_body(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(method="POST", path="/post/", query_string="echo=1")
        protocol = MockRSGIProtocol(body=b"Echo RSGI")

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        self.assertEqual(protocol.response["body"], b"Echo RSGI")

    async def test_rsgi_cookies(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(path="/cookie/")
        protocol = MockRSGIProtocol()

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        headers = protocol.response["headers"]
        self.assertIn(("Set-Cookie", "key=value; Path=/"), headers)

    async def test_rsgi_headers(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(
            path="/meta/",
            headers={
                "referer": "http://example.com",
                "content-type": "application/json",
            },
        )
        protocol = MockRSGIProtocol()

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        self.assertEqual(protocol.response["body"], b"From http://example.com")
        headers = dict(protocol.response["headers"])
        self.assertEqual(headers["Content-Type"], "application/json")

    async def test_rsgi_file_response(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(path="/file/")
        protocol = MockRSGIProtocol()

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        headers = dict(protocol.response["headers"])
        self.assertEqual(headers["Content-Type"], "text/x-python")

        from tests.urls import test_filename

        with open(test_filename, "rb") as f:
            self.assertEqual(protocol.response["body"], f.read())

    async def test_rsgi_streaming_response(self):
        application = get_rsgi_application()
        scope = MockRSGIScope(path="/streaming/")
        protocol = MockRSGIProtocol()

        await application(scope, protocol)

        self.assertEqual(protocol.response["status"], 200)
        # For streaming, the MockRSGIProtocol stores the sent_data list in "body"
        chunks = protocol.response["body"]
        self.assertEqual(b"".join(chunks), b"first\nlast\n")
