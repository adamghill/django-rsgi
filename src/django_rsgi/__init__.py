import django

from .handler import RSGIHandler


def get_rsgi_application():
    """The public interface to Django's RSGI support. Return an RSGI callable."""

    django.setup(set_prefix=False)

    return RSGIHandler()
