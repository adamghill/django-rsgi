from django.http import HttpResponse


async def index(request):
    return HttpResponse(
        "<h1>Django RSGI is running!</h1><p>Served by Granian via RSGI.</p>"
    )


async def hello(request, name):
    return HttpResponse(f"Hello, {name}!")
