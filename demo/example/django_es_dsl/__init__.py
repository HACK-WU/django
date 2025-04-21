# coding=utf-8
from example.django_es_dsl.models import initial_models, READY_INITIAL_DATA

# 初始化model数据
# 同步数据到es需要手动执行： python manage.py rebuild_es
if not READY_INITIAL_DATA:
    initial_models()
