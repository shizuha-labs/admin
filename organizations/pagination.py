"""Pagination helpers for Admin APIs served behind the public /admin mount."""
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from rest_framework.pagination import PageNumberPagination


class AdminPublicPageNumberPagination(PageNumberPagination):
    """Return public pagination links when nginx strips the /admin prefix.

    The Admin Django app receives upstream paths like ``/api/...`` while the
    browser/client sees ``/admin/api/...``. DRF's default PageNumberPagination
    correctly preserves query params but builds absolute links from the upstream
    request, which drops the public mount path. Rewrite only the generated API
    links so clients can follow ``next``/``previous`` directly.
    """

    def get_next_link(self):
        return self._public_link(super().get_next_link())

    def get_previous_link(self):
        return self._public_link(super().get_previous_link())

    def _public_link(self, link):
        if not link:
            return link

        parts = urlsplit(link)
        path = self._public_path(parts.path)
        scheme = self._public_scheme(parts.scheme)
        netloc = self._public_host(parts.netloc)
        return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))

    def _public_path(self, path):
        internal_prefix = (
            getattr(settings, 'ADMIN_INTERNAL_API_PREFIX', '/api').rstrip('/')
            or '/api'
        )
        public_prefix = (
            getattr(settings, 'ADMIN_PUBLIC_API_PREFIX', '/admin/api').rstrip('/')
            or '/admin/api'
        )

        if path == internal_prefix:
            return public_prefix
        if path.startswith(f'{internal_prefix}/'):
            return f'{public_prefix}{path[len(internal_prefix):]}'
        return path

    def _public_scheme(self, fallback):
        request = getattr(self, 'request', None)
        if not request:
            return fallback
        forwarded = request.META.get('HTTP_X_FORWARDED_PROTO', '')
        if forwarded:
            return forwarded.split(',', 1)[0].strip() or fallback
        return getattr(settings, 'ADMIN_PUBLIC_SCHEME', '') or fallback

    def _public_host(self, fallback):
        request = getattr(self, 'request', None)
        if not request:
            return fallback
        forwarded = request.META.get('HTTP_X_FORWARDED_HOST', '')
        if forwarded:
            return forwarded.split(',', 1)[0].strip() or fallback
        return fallback
