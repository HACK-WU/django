# coding=utf-8
# Time: 2025/4/20 21:03
# name: utils
# author: HACK-WU

from app01.models import InitialModels
from app01.ser import InitialModelsSerializer
from rest_framework import serializers


# class ProcessModel:
#
#     def __init__(self, serializer=None, data=None):
#         self.serializer = serializer
#         self.data = data
#
#     def bulk_create(self):
#         """
#         批量创建数据
#         :return:
#         """
#
#     def delete_data(self):
#         """
#         删除数据
#         :return:
#         """
#         self.serializer.objects.all().delete()
#
#     def initial_data(self):
#         """
#         初始化数据
#         :return:
#         """
#         if self.serializer.objects.count() < len(self.data):
#             self.delete_data()
#             instance = self.bulk_create(self.data)
#         else:
#             instance = self.serializer.objects.none()
#
#         return instance
#
#     @property
#     def name(self):
#         return self.serializer.__name__
#

def get_table_name(ser):
    if isinstance(ser, serializers.ListSerializer):
        model = ser.child.Meta.model
    else:
        model = ser.Meta.model

    return model.__name__


def initial_data(ser: serializers.ModelSerializer):
    table_name = get_table_name(ser)
    if not InitialModels.objects.filter(model_name=table_name).exists():
        ser.is_valid(raise_exception=True)
        ser.save()
        initial = InitialModelsSerializer(
            data={"model_name": table_name, "model_data": ser.data})
        initial.is_valid(raise_exception=True)
        initial.save()
