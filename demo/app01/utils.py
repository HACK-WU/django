# coding=utf-8
# Time: 2025/4/20 21:03
# name: utils
# author: HACK-WU

from app01.models import InitialModels
from app01.ser import InitialModelsSerializer
from rest_framework import serializers


def get_table_name(ser):
    if isinstance(ser, serializers.ListSerializer):
        model = ser.child.Meta.model
    else:
        model = ser.Meta.model

    return model.__name__


def clear_data(ser):
    if isinstance(ser, serializers.ListSerializer):
        model = ser.child.Meta.model
    else:
        model = ser.Meta.model
    model.objects.all().delete()


def initial_data(ser: serializers.ModelSerializer):
    table_name = get_table_name(ser)
    if not InitialModels.objects.filter(model_name=table_name).exists():
        clear_data(ser)
        ser.is_valid(raise_exception=True)
        ser.save()

        initial = InitialModelsSerializer(
            data={"model_name": table_name, "model_data": ser.data})
        initial.is_valid(raise_exception=True)
        initial.save()
