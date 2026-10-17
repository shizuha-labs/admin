"""
URL configuration for Shizuha Admin.

In K3s deployment, nginx proxies:
- /admin/api/ -> http://shizuha-admin/api/
So we use /api/ prefix here (nginx strips /admin/).
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from organizations.security_events import boundary_event_metrics


def health_check(request):
    """Simple health check endpoint for container health checks."""
    return JsonResponse({'status': 'healthy'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('organizations.urls')),
    path('api/internal/', include('organizations.internal_urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/health/', health_check, name='health-check'),
    path('api/metrics/security-events/', boundary_event_metrics, name='security-event-metrics'),
]
