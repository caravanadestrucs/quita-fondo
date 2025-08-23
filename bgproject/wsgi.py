"""
Configuración WSGI para el proyecto bgproject.

Este archivo expone la aplicación WSGI como una variable de nivel de módulo llamada `application`.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bgproject.settings')

application = get_wsgi_application()
