# coding=utf-8
# Time: 2025/4/20 20:50
# name: index
# author: HACK-WU

from elasticsearch.dsl import Index
from django_elasticsearch_dsl import Document
from example.es.models import Car, Manufacturer
from django_elasticsearch_dsl.registries import registry

# The name of your index
car = Index('cars')
# See Elasticsearch Indices API reference for available settings
car.settings(
    number_of_shards=1,
    number_of_replicas=0
)


@registry.register_document
@car.document
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
        name = 'manufacture'
        settings = {'number_of_shards': 1,
                    'number_of_replicas': 0}

    class Django:
        model = Manufacturer
        fields = [
            'name',
            'country_code',
        ]
