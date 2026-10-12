# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from importlib.util import find_spec

import dj_database_url

# Postgres required; CI provides DATABASE_URL, locally point it at any postgres 15+
# (default matches the CI service).
DATABASES = {
    "default": dj_database_url.config(default="postgresql://postgres:postgres@localhost:5432/test"),
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_regional",
    "django_pricemanager",
    "rest_framework",
]
# django_access when importable (zeno): tests/test_access_ownership.py proves the access declarations.
if find_spec("django_access"):
    INSTALLED_APPS.append("django_access")

SECRET_KEY = "test-secret-key"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

ROOT_URLCONF = "tests.urls"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# Required by bi.py (bievents)
BI_ENVIRONMENT = "test"
BI_BUSINESS_UNIT = "test"

# Celery (tasks import celery_once)
ONCE = {"url": "redis://localhost:6379/0", "blocking_timeout": 1}
CELERY_ONCE = ONCE
