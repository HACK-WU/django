# coding=utf-8
# Time: 2025/4/18 22:43
# name: shell
# author: HACK-WU


import hello
from example.django_es_dsl.models import manufacturer_infos, models
from app01.ser import ManufacturerSerializer

from django_elasticsearch_dsl.signals import post_index
