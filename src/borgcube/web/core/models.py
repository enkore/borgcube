
from django.db import models


class OverviewMetric(models.Model):
    py_class = models.CharField(max_length=100)
    label = models.CharField(max_length=100)
    order = models.IntegerField(default=0)

    # TODO support parameters?
    class Meta:
        ordering = ['order',]
