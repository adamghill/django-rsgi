import io

from django.test import SimpleTestCase

from django_rsgi.handler import RSGIHandler, RSGIRequest

from .mocks import MockRSGIScope


class RSGIRequestTests(SimpleTestCase):
    def test_request_meta_headers(self):
        scope = MockRSGIScope(
            headers={
                "content-type": "application/json",
                "content-length": "42",
                "user-agent": "test-agent",
                "x-custom": "value",
            }
        )
        request = RSGIRequest(scope, io.BytesIO(b""))

        self.assertEqual(request.META["CONTENT_TYPE"], "application/json")
        self.assertEqual(request.META["CONTENT_LENGTH"], "42")
        self.assertEqual(request.META["HTTP_USER_AGENT"], "test-agent")
        self.assertEqual(request.META["HTTP_X_CUSTOM"], "value")

    def test_request_meta_client_server(self):
        scope = MockRSGIScope(client="1.2.3.4:5678", server="8.8.8.8:80")
        request = RSGIRequest(scope, io.BytesIO(b""))

        self.assertEqual(request.META["REMOTE_ADDR"], "1.2.3.4")
        self.assertEqual(request.META["REMOTE_PORT"], 5678)
        self.assertEqual(request.META["SERVER_NAME"], "8.8.8.8")
        self.assertEqual(request.META["SERVER_PORT"], "80")

    def test_request_meta_client_malformed(self):
        scope = MockRSGIScope(client="not-an-ip", server=None)
        request = RSGIRequest(scope, io.BytesIO(b""))

        self.assertEqual(request.META["REMOTE_ADDR"], "not-an-ip")
        self.assertEqual(request.META["SERVER_NAME"], "unknown")

    def test_path_info_with_script_name(self):
        scope = MockRSGIScope(path="/prefix/foo/bar")
        scope.root_path = "/prefix"
        request = RSGIRequest(scope, io.BytesIO(b""))

        self.assertEqual(request.path, "/prefix/foo/bar")
        self.assertEqual(request.path_info, "/foo/bar")
        self.assertEqual(request.script_name, "/prefix")


class RSGIHandlerTests(SimpleTestCase):
    def test_create_request_success(self):
        handler = RSGIHandler()
        scope = MockRSGIScope()
        body_file = io.BytesIO(b"test body")
        request, error = handler.create_request(scope, body_file)

        self.assertIsInstance(request, RSGIRequest)
        self.assertIsNone(error)
        self.assertEqual(request.body, b"test body")
