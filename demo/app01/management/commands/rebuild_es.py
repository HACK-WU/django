# coding=utf-8
# Time: 2025/4/18 23:09
# name: rebuild_es
# author: HACK-WU
from django.core.management.base import BaseCommand
from django_elasticsearch_dsl.registries import registry
from example.django_es_dsl import document


class Command(BaseCommand):
    """
    在当前版本中，该命令./manage.py search_index --rebuild 失效
    所以使用该文件来代替
    """
    help = '通用 ES 索引重建命令 (自动处理所有注册的 Document)'

    def handle(self, *args, **options):
        # 获取所有注册的 Document 类
        for doc_class in registry.get_documents():
            self.stdout.write(f"正在处理: {doc_class.Index.name}")

            # 获取关联的 Django 模型
            model = doc_class.Django.model
            # 创建新索引
            doc_class.init()
            self.stdout.write(f"已创建索引: {doc_class.Index.name}")

            count = 0
            for obj in model.objects.all():
                doc_class().update(obj)
                count += 1

            self.stdout.write(
                self.style.SUCCESS(f"已导入 {count} 条数据到 {doc_class.Index.name}"))

        self.stdout.write(self.style.SUCCESS('所有索引重建完成'))
