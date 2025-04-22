import hello
from django.conf import settings

# 是否强制重建模型数据
FORCE_REBUILD_MODEL_DATA = False

if FORCE_REBUILD_MODEL_DATA or getattr(settings, "FORCE_REBUILD_MODEL_DATA", False):
    from app01.models import InitialModels

    InitialModels.objects.all().delete()

from example.django_es_dsl import models

# 直接执该脚本即可创建数据
