import asyncio
import logging
import sys
import tempfile
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


def get_script_prefix(scope):
    """
    Return the script prefix to use from either the scope or a setting.
    """
    if settings.FORCE_SCRIPT_NAME:
        return settings.FORCE_SCRIPT_NAME
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
        self.path = scope.path
        self.script_name = get_script_prefix(scope)
        if self.script_name:
            self.path_info = scope.path.removeprefix(self.script_name)
        else:
            self.path_info = scope.path
        # HTTP basics.
        self.method = scope.method.upper()
        # Ensure query string is handled.
        query_string = scope.query_string or ""
        self.META = {
            "REQUEST_METHOD": self.method,
            "QUERY_STRING": query_string,
            "SCRIPT_NAME": self.script_name,
            "PATH_INFO": self.path_info,
            "wsgi.multithread": True,
            "wsgi.multiprocess": True,
        }
        if scope.client:
            try:
                host, port = scope.client.rsplit(":", 1)
                self.META["REMOTE_ADDR"] = host
                self.META["REMOTE_HOST"] = host
                self.META["REMOTE_PORT"] = int(port)
            except ValueError:
                self.META["REMOTE_ADDR"] = scope.client
        if scope.server:
            try:
                host, port = scope.server.rsplit(":", 1)
                self.META["SERVER_NAME"] = host
                self.META["SERVER_PORT"] = str(port)
            except ValueError:
                self.META["SERVER_NAME"] = scope.server
        else:
            self.META["SERVER_NAME"] = "unknown"
            self.META["SERVER_PORT"] = "0"

        # Headers go into META.
        for name in scope.headers:
            if name == "content-length":
                corrected_name = "CONTENT_LENGTH"
            elif name == "content-type":
                corrected_name = "CONTENT_TYPE"
            else:
                corrected_name = "HTTP_%s" % name.upper().replace("-", "_")

            values = scope.headers.get_all(name)
            value = ",".join(values)

            if corrected_name == "HTTP_COOKIE":
                value = value.rstrip("; ")
                if "HTTP_COOKIE" in self.META:
                    value = self.META[corrected_name] + "; " + value
            elif corrected_name in self.META:
                value = self.META[corrected_name] + "," + value
            self.META[corrected_name] = value

        # Pull out request encoding, if provided.
        self._set_content_type_params(self.META)
        # Directly assign the body file to be our stream.
        self._stream = body_file
        # Other bits.
        self.resolver_match = None

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

        body_file = tempfile.SpooledTemporaryFile(
            max_size=settings.FILE_UPLOAD_MAX_MEMORY_SIZE, mode="w+b"
        )
        body_file.write(body)
        body_file.seek(0)

        with closing(body_file):
            set_script_prefix(get_script_prefix(scope))
            await signals.request_started.asend(sender=self.__class__, scope=scope)
            # Get the request and check for basic issues.
            request, error_response = self.create_request(scope, body_file)
            if request is None:
                await self.send_response(error_response, protocol)
                await sync_to_async(error_response.close)()
                return

            class RequestProcessed(Exception):
                pass

            response = None
            try:
                try:
                    async with asyncio.TaskGroup() as tg:

                        async def watch_disconnect():
                            await protocol.client_disconnect()
                            raise RequestAborted()

                        tg.create_task(watch_disconnect())
                        response = await self.run_get_response(request)
                        await self.send_response(response, protocol)
                        raise RequestProcessed
                except* (RequestProcessed, RequestAborted):
                    pass
            except BaseExceptionGroup as exception_group:
                if len(exception_group.exceptions) == 1:
                    raise exception_group.exceptions[0]
                raise

            if response is None:
                await signals.request_finished.asend(sender=self.__class__)
            else:
                await sync_to_async(response.close)()

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
        response_headers = []
        for header, value in response.items():
            response_headers.append((header, value))
        for c in response.cookies.values():
            response_headers.append(("Set-Cookie", c.OutputString()))

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
