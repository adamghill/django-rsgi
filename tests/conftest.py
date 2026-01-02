import django
from django.conf import settings


def pytest_configure():
    settings.configure(
        SECRET_KEY="django-insecure-secret-key",
        ALLOWED_HOSTS=["*"],
        ROOT_URLCONF="tests.urls",
        INSTALLED_APPS=[],
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
    )

    django.setup()
