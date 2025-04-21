# coding=utf-8
# Time: 2025/4/20 20:50
# name: index
# author: HACK-WU

from elasticsearch.dsl import Index
# django_elasticsearch_dsl <=7.0 时使用下面的导入方式
# from elasticsearch_dsl import Index
from django_elasticsearch_dsl import Document
from example.django_es_dsl.models import Car, Manufacturer
from django_elasticsearch_dsl.registries import registry

# 参考文档：https://django-elasticsearch-dsl.readthedocs.io/en/latest/es_index.html

# 单独创建索引
car = Index('cars')
# See Elasticsearch Indices API reference for available settings
car.settings(
    number_of_shards=1,  # 设置分片数量
    number_of_replicas=0  # 设置副本数量
)


@registry.register_document
@car.document  # 将car索引与Car模型关联
class CarDocument(Document):
    class Django:
        model = Car
        fields = [
            'name',
            'color',
        ]


@registry.register_document
class ManufacturerDocument(Document):
    class Index:
        name = 'manufacture'  # 指定索引名称
        settings = {'number_of_shards': 1,
                    'number_of_replicas': 0}

    class Django:
        model = Manufacturer
        fields = [
            'name',
            'country_code',
        ]

# 执行$ ./manage.py search_index --rebuild 命令
# 这将在 Elasticsearch 中创建两个名为 cars 和 manufacture 的索引，并带有适当的映射
