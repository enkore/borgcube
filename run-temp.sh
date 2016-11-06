#!/bin/sh -xue

# TODO we want to do it like eg. pootle, with a custom django-admin wrapper & ~/.borgcube/borgcube.conf|py
DJANGO_SETTINGS_MODULE=borgcube.web.settings django-admin ${@:-runserver}
