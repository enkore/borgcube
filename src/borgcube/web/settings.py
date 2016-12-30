"""
Django settings for web project.

Generated by 'django-admin startproject' using Django 1.10.2.

For more information on this file, see
https://docs.djangoproject.com/en/1.10/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.10/ref/settings/
"""

import os
from pathlib import Path
from pkg_resources import iter_entry_points

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.10/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'b&ug*)9a9r@_*fr8pux@p)0&=$pu4ecy!n((ljzqm=py(6oo9w'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

for entry_point in iter_entry_points('borgcube0_apps'):
    INSTALLED_APPS.append(entry_point.module_name)
    if os.environ.get('BORGCUBE_DEBUG_APP_LOADING'):
        # This is so early in the startup process that logging won't be configured.
        print('Discovered Django application through distribution %s: %s (%s)' % (
            entry_point.dist, entry_point.name, entry_point.module_name,
        ))

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'borgcube.web.core.middleware.transaction_middleware',
]

ROOT_URLCONF = 'borgcube.web.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            str(Path(__file__).parent / 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'borgcube.web.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/1.10/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/1.10/topics/i18n/

LANGUAGE_CODE = 'de-DE'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.10/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    str(Path(__file__).parent / 'static'),
]


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(asctime)s] %(process)-4d %(levelname)-8s %(name)s: %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        'django.db': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        '': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'borg.key': {
            'level': 'WARNING',
        },

        'ZEO': {
            'level': 'WARNING',
        },
        'txn': {
            'level': 'WARNING',
        },
        'asyncio': {
            'level': 'WARNING',
        },
    },
}

# TODO XXX this should be in the base package no?

# SERVER_CACHE_DIR = '~/'

SERVER_LOGS_DIR = str(Path(__file__).parent.parent.parent.parent / '_logs')

SERVER_LOGIN = 'mabe@localhost'

# This can usually be left empty. It is only needed if no SSH forced commands are used.
# (This is then passed as the --remote-path option to the Borg running on the client)
SERVER_PROXY_PATH = None
SERVER_PROXY_PATH = '/home/mabe/Projekte/_oss/borgcube/_venv/bin/borgcube-proxy'

DAEMON_ADDRESS = 'tcp://127.0.0.1:58123'

# By default borgcubed will run a DB server. If you want to provide the DB server
# yourself or use eg. RelStorage, turn this off.
BUILTIN_ZEO = True

SOCKET_PREFIX = '/run/user/{euid}/borgcube'

# zodburi ( http://docs.pylonsproject.org/projects/zodburi/en/latest/ ) of the DB to use
# note: file:// paths are always absolute.
DB_URI = 'file:///home/mabe/Projekte/_oss/borgcube/_db/Data.fs'


# borgcubed can also run the web server itself, so you don't need to care about that,
# if you like.
# BUILTIN_WEB = '127.0.0.1:8002'
BUILTIN_WEB = False
