# coding=utf-8
# Time: 2025/4/20 22:38
# name: ser
# author: HACK-WU
from app01 import models
from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

class CarSerializer(BaseModelSerializer):
    class Meta:
        model = models.Car
        fields = "__all__"


class ManufacturerSerializer(BaseModelSerializer):
    class Meta:
        model = models.Manufacturer
        fields = "__all__"


class InitialModelsSerializer(BaseModelSerializer):
    class Meta:
        model = models.InitialModels
        fields = "__all__"


class AdSerializer(BaseModelSerializer):
    class Meta:
        model = models.Ad
        fields = "__all__"
