import asyncio


class MockRSGIHeaders:
    def __init__(self, headers):
        self._headers = headers

    def __iter__(self):
        return iter(self._headers.keys())

    def get_all(self, name):
        val = self._headers.get(name.lower())
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return [val]

    def get(self, name):
        return self._headers.get(name.lower())


class MockRSGIScope:
    def __init__(
        self,
        method="GET",
        path="/",
        query_string="",
        headers=None,
        client="127.0.0.1:1234",
        server="127.0.0.1:80",
    ):
        self.proto = "http"
        self.method = method
        self.path = path
        self.query_string = query_string
        self.client = client
        self.server = server
        self.headers = MockRSGIHeaders(headers or {})
        self.scheme = "http"
        self.rsgi_version = "1.0"
        self.http_version = "1.1"
        self.root_path = ""


class MockRSGITransport:
    def __init__(self):
        self.sent_data = []

    async def send_bytes(self, data):
        self.sent_data.append(data)

    async def send_str(self, data):
        self.sent_data.append(data.encode("utf-8"))


class MockRSGIProtocol:
    def __init__(self, body=b""):
        self.body = body
        self.response = None
        self.transport = MockRSGITransport()
        self.disconnected = asyncio.Future()

    async def __call__(self):
        return self.body

    async def client_disconnect(self):
        await self.disconnected

    def response_empty(self, status, headers):
        self.response = {"status": status, "headers": headers, "body": b""}

    def response_str(self, status, headers, body):
        self.response = {
            "status": status,
            "headers": headers,
            "body": body.encode("utf-8"),
        }

    def response_bytes(self, status, headers, body):
        self.response = {"status": status, "headers": headers, "body": body}

    def response_file(self, status, headers, file):
        with open(file, "rb") as f:
            self.response = {"status": status, "headers": headers, "body": f.read()}

    def response_stream(self, status, headers):
        self.response = {
            "status": status,
            "headers": headers,
            "body": self.transport.sent_data,
        }
        return self.transport
