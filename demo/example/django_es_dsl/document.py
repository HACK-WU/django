from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from app01 import models


# https://django-elasticsearch-dsl.readthedocs.io/en/latest/quickstart.html
@registry.register_document
class CarDocument(Document):
    # add a string field to the Elasticsearch mapping called type, the
    # value of which is derived from the model's type_to_string attribute
    # https://django-elasticsearch-dsl.readthedocs.io/en/latest/fields.html
    type = fields.TextField(attr="type_to_string")

    color = fields.TextField()

    class Index:
        # Name of the Elasticsearch index
        name = 'cars'
        # See Elasticsearch Indices API reference for available settings
        settings = {'number_of_shards': 1,
                    'number_of_replicas': 0}

    class Django:
        model = models.Car  # 与当前document关联的模型

        # 要在Elasticsearch中检索的字段
        fields = [
            'name',
            # 'color',  # 显示声明以后，这里不需要再声明
            'description',
            # 'type',
        ]

        # 当模型保存或删除时，忽略自动更新Elasticsearch
        # ignore_signals = True

        # 配置更新后索引的刷新方式
        # 可用的设置选项参考Elasticsearch文档：
        # https://www.elastic.co/guide/en/elasticsearch/reference/master/docs-refresh.html
        # 该每个Document的设置会覆盖全局设置settings.ELASTICSEARCH_DSL_AUTO_REFRESH
        # auto_refresh = False

        # 对用于填充索引的Django查询集进行分页，指定分页大小
        # （默认使用数据库驱动的默认设置）
        # queryset_pagination = 5000

    # 有时候，在将字段保存到 Elasticsearch 之前，您需要做一些额外的准备工作。
    # 您可以通过在Document类中定义一个名为prepare_[field_name]的函数来实现这一点。
    # 这个函数应该接受一个模型实例作为参数，并返回一个值，该值将被存储在 Elasticsearch 中。
    def prepare_color(self, instance):
        """
        将颜色转换为大写
        """
        return instance.color.upper()
