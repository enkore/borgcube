# -*- coding: utf-8 -*-
# Generated by Django 1.10.3 on 2016-11-08 14:37
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='job',
            old_name='state',
            new_name='db_state',
        ),
    ]