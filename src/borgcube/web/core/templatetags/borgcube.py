
from django import template
from django.urls import reverse

from borgcube.core import models
from .. import views

register = template.Library()


@register.filter
def field_name(model_instance, field):
    # TODO want the exact same behaviour as django has built in (name -> Name)
    return model_instance._meta.get_field(field).verbose_name


@register.filter
def help_text(model_instance, field):
    return model_instance._meta.get_field(field).help_text


@register.filter
def get_url(model_instance):
    obj = model_instance
    if isinstance(obj, models.Job):
        return reverse(views.job_view, args=(obj.client.pk, obj.pk))
    elif isinstance(obj, models.Client):
        return reverse(views.client_view, args=(obj.pk,))
    elif isinstance(obj, models.JobConfig):
        return reverse(views.client_view, args=(obj.client.pk,)) + '#job-config-%d' % obj.pk
    else:
        raise ValueError('Can\'t generate URL for %r (type %r)' % (obj, type(obj)))


@register.filter
def compression_name(compression_id):
    return dict(views.JobConfigForm.COMPRESSION_CHOICES).get(compression_id, compression_id)
