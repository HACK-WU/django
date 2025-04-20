# coding=utf-8
# Time: 2025/4/20 22:38
# name: ser
# author: HACK-WU
from app01 import models
from rest_framework import serializers


class CarSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Car
        fields = "__all__"


class ManufacturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Manufacturer
        fields = "__all__"


class InitialModelsSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.InitialModels
        fields = "__all__"
