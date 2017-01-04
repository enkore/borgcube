import posixpath
import os
import os.path
import stat
import mimetypes

from django.http import Http404
from django.views.static import was_modified_since
from django.http import HttpResponseNotModified, FileResponse
from django.utils.http import http_date
from django.conf import settings


def staticfiles(request, file):
    """
    Simple view for serving static files directly from STATICFILES_DIRS.

    Does not allow subdirectories. Does do If-Modified-Since, though.

    Based on `django.views.static.serve`.
    """
    if '/..\\' in file:
        raise Http404
    if posixpath.normpath(file) != file:
        raise Http404

    for static_file_dir in settings.STATICFILES_DIRS:
        fullpath = os.path.abspath(os.path.join(static_file_dir, file))
        if not fullpath.startswith(static_file_dir):
            raise Http404
        try:
            st = os.stat(fullpath)
        except FileNotFoundError:
            continue
        break
    else:
        raise Http404

    if not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'),
                              st.st_mtime, st.st_size):
        return HttpResponseNotModified()
    content_type, encoding = mimetypes.guess_type(fullpath)
    content_type = content_type or 'application/octet-stream'
    response = FileResponse(open(fullpath, 'rb'), content_type=content_type)
    response['Last-Modified'] = http_date(st.st_mtime)
    if stat.S_ISREG(st.st_mode):
        response['Content-Length'] = st.st_size
    if encoding:
        response['Content-Encoding'] = encoding
    return response
