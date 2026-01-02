import asyncio

from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt


def hello(request):
    name = request.GET.get("name") or "World"
    return HttpResponse("Hello %s!" % name)


def hello_meta(request):
    return HttpResponse(
        "From %s" % (request.META.get("HTTP_REFERER") or ""),
        content_type=request.META.get("CONTENT_TYPE"),
    )


def hello_cookie(request):
    response = HttpResponse("Hello World!")
    response.set_cookie("key", "value")
    return response


@csrf_exempt
def post_echo(request):
    if request.GET.get("echo"):
        return HttpResponse(request.body)
    else:
        return HttpResponse(status=204)


async def streaming_inner(sleep_time):
    yield b"first\n"
    await asyncio.sleep(sleep_time)
    yield b"last\n"


async def streaming_view(request):
    sleep_time = float(request.GET.get("sleep", 0))
    return StreamingHttpResponse(streaming_inner(sleep_time))


test_filename = __file__


urlpatterns = [
    path("", hello),
    path("cookie/", hello_cookie),
    path("file/", lambda x: FileResponse(open(test_filename, "rb"))),
    path("meta/", hello_meta),
    path("post/", post_echo),
    path("streaming/", streaming_view),
]
