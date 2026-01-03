import io
import logging
import sys
import traceback
from contextlib import aclosing, closing

from asgiref.sync import ThreadSensitiveContext, sync_to_async
from django.conf import settings
from django.core import signals
from django.core.exceptions import RequestAborted, RequestDataTooBig
from django.core.handlers import base
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseServerError,
    QueryDict,
    parse_cookie,
)
from django.urls import set_script_prefix
from django.utils.functional import cached_property

logger = logging.getLogger("django.request")

# Pre-populated cache for common header names to avoid redundant string manipulation
_HEADER_NAME_CACHE = {
    "accept": "HTTP_ACCEPT",
    "accept-encoding": "HTTP_ACCEPT_ENCODING",
    "accept-language": "HTTP_ACCEPT_LANGUAGE",
    "authorization": "HTTP_AUTHORIZATION",
    "connection": "HTTP_CONNECTION",
    "content-length": "CONTENT_LENGTH",
    "content-type": "CONTENT_TYPE",
    "cookie": "HTTP_COOKIE",
    "host": "HTTP_HOST",
    "referer": "HTTP_REFERER",
    "user-agent": "HTTP_USER_AGENT",
    "x-real-ip": "HTTP_X_REAL_IP",
    "x-forwarded-for": "HTTP_X_FORWARDED_FOR",
    "x-forwarded-proto": "HTTP_X_FORWARDED_PROTO",
    "x-forwarded-host": "HTTP_X_FORWARDED_HOST",
    "x-forwarded-port": "HTTP_X_FORWARDED_PORT",
    "x-requested-with": "HTTP_X_REQUESTED_WITH",
}


def get_normalized_header_name(name):
    """
    Map an RSGI header name to a WSGI-style META key.
    """
    try:
        return _HEADER_NAME_CACHE[name]
    except KeyError:
        if name == "content-length":
            res = "CONTENT_LENGTH"
        elif name == "content-type":
            res = "CONTENT_TYPE"
        else:
            res = f"HTTP_{name.upper().replace('-', '_')}"
        _HEADER_NAME_CACHE[name] = res
        return res


def get_script_prefix(scope):
    """
    Return the script prefix to use from either the scope or a setting.
    """
    if force_script_name := settings.FORCE_SCRIPT_NAME:
        return force_script_name
    return getattr(scope, "root_path", "")


class RSGIRequest(HttpRequest):
    """
    Custom request subclass that decodes from an RSGI-standard request object
    and wraps request body handling.
    """

    def __init__(self, scope, body_file):
        self.scope = scope
        self._post_parse_error = False
        self._read_started = False
        self.resolver_match = None

        path = scope.path
        self.path = path

        script_name = get_script_prefix(scope)
        self.script_name = script_name

        # Optimization: Only perform removeprefix if script_name is not empty
        if script_name:
            self.path_info = path.removeprefix(script_name)
        else:
            self.path_info = path

        # Optimization: RSGI spec guarantees method is already uppercased
        method = scope.method
        self.method = method

        # Initialize META with basic info
        self.META = {
            "REQUEST_METHOD": method,
            "QUERY_STRING": scope.query_string or "",
            "SCRIPT_NAME": script_name,
            "PATH_INFO": self.path_info,
            "wsgi.multithread": True,
            "wsgi.multiprocess": True,
        }

        # Client/Server parsing
        client = scope.client
        if client:
            try:
                host, port = client.rsplit(":", 1)
                self.META["REMOTE_ADDR"] = host
                self.META["REMOTE_HOST"] = host
                self.META["REMOTE_PORT"] = int(port)
            except ValueError:
                self.META["REMOTE_ADDR"] = client

        server = scope.server
        if server:
            try:
                host, port = server.rsplit(":", 1)
                self.META["SERVER_NAME"] = host
                self.META["SERVER_PORT"] = str(port)
            except ValueError:
                self.META["SERVER_NAME"] = server
        else:
            self.META["SERVER_NAME"] = "unknown"
            self.META["SERVER_PORT"] = "0"

        # Headers normalization loop
        meta = self.META
        headers = scope.headers
        for name in headers:
            corrected_name = get_normalized_header_name(name)

            # Using get_all to join multiple header values as per Django standards
            values = headers.get_all(name)
            value = ",".join(values)

            if corrected_name == "HTTP_COOKIE":
                value = value.rstrip("; ")
                if "HTTP_COOKIE" in meta:
                    value = meta["HTTP_COOKIE"] + "; " + value
            elif corrected_name in meta:
                value = meta[corrected_name] + "," + value

            meta[corrected_name] = value

        # Pull out request encoding, if provided.
        self._set_content_type_params(meta)
        # Directly assign the body file to be our stream.
        self._stream = body_file

    @cached_property
    def GET(self):
        return QueryDict(self.META["QUERY_STRING"])

    def _get_scheme(self):
        return self.scope.scheme or super()._get_scheme()

    def _get_post(self):
        if not hasattr(self, "_post"):
            self._load_post_and_files()
        return self._post

    def _set_post(self, post):
        self._post = post

    def _get_files(self):
        if not hasattr(self, "_files"):
            self._load_post_and_files()
        return self._files

    POST = property(_get_post, _set_post)
    FILES = property(_get_files)

    @cached_property
    def COOKIES(self):
        return parse_cookie(self.META.get("HTTP_COOKIE", ""))

    def close(self):
        super().close()
        self._stream.close()


class RSGIHandler(base.BaseHandler):
    """Handler for RSGI requests."""

    request_class = RSGIRequest
    chunk_size = 2**16

    def __init__(self):
        super().__init__()
        self.load_middleware(is_async=True)

    async def __call__(self, scope, protocol):
        """
        Async entrypoint - parses the request and hands off to get_response.
        """
        if scope.proto != "http":
            return

        async with ThreadSensitiveContext():
            await self.handle(scope, protocol)

    async def handle(self, scope, protocol):
        """
        Handles the RSGI request.
        """
        try:
            body = await protocol()
        except Exception:
            return

        with closing(io.BytesIO(body)) as body_file:
            script_prefix = get_script_prefix(scope)
            set_script_prefix(script_prefix)

            # Optimization: Skip signal emission if no receivers connected
            if signals.request_started.receivers:
                await signals.request_started.asend(sender=self.__class__, scope=scope)

            # Get the request and check for basic issues.
            request, error_response = self.create_request(scope, body_file)
            if request is None:
                await self.send_response(error_response, protocol)
                await sync_to_async(error_response.close)()
                return

            response = None
            try:
                response = await self.run_get_response(request)
                await self.send_response(response, protocol)
            except RequestAborted:
                pass
            finally:
                if response is not None:
                    await sync_to_async(response.close)()

            if response is None:
                if signals.request_finished.receivers:
                    await signals.request_finished.asend(sender=self.__class__)

    async def run_get_response(self, request):
        """Get async response."""
        response = await self.get_response_async(request)
        response._handler_class = self.__class__
        if isinstance(response, FileResponse):
            response.block_size = self.chunk_size
        return response

    def create_request(self, scope, body_file):
        """
        Create the Request object and returns either (request, None) or
        (None, response) if there is an error response.
        """
        try:
            return self.request_class(scope, body_file), None
        except UnicodeDecodeError:
            logger.warning(
                "Bad Request (UnicodeDecodeError)",
                exc_info=sys.exc_info(),
                extra={"status_code": 400},
            )
            return None, HttpResponseBadRequest()
        except RequestDataTooBig:
            return None, HttpResponse("413 Payload too large", status=413)

    def handle_uncaught_exception(self, request, resolver, exc_info):
        """Last-chance handler for exceptions."""
        try:
            return super().handle_uncaught_exception(request, resolver, exc_info)
        except Exception:
            return HttpResponseServerError(
                traceback.format_exc() if settings.DEBUG else "Internal Server Error",
                content_type="text/plain",
            )

    async def send_response(self, response, protocol):
        """Encode and send a response out over RSGI."""
        response_headers = [(header, value) for header, value in response.items()]
        if response.cookies:
            # OutputString() is relatively slow but necessary
            response_headers.extend(
                ("Set-Cookie", c.OutputString()) for c in response.cookies.values()
            )

        # Optimization for file responses.
        if (
            isinstance(response, FileResponse)
            and hasattr(response, "file_to_stream")
            and hasattr(response.file_to_stream, "name")
        ):
            try:
                protocol.response_file(
                    response.status_code,
                    response_headers,
                    response.file_to_stream.name,
                )
                return
            except Exception:
                pass

        if response.streaming:
            transport = protocol.response_stream(response.status_code, response_headers)
            async with aclosing(aiter(response)) as content:
                async for part in content:
                    if isinstance(part, str):
                        await transport.send_str(part)
                    else:
                        await transport.send_bytes(part)
        else:
            protocol.response_bytes(
                response.status_code, response_headers, response.content
            )
