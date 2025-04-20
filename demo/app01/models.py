from django.db import models


class BaseModel(models.Model):
    class Meta:
        abstract = True


# https://django-elasticsearch-dsl.readthedocs.io/en/latest/quickstart.html
class Car(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    color = models.CharField(max_length=255)
    description = models.TextField()
    type = models.IntegerField(choices=[
        (1, "Sedan"),
        (2, "Truck"),
        (3, "SUV"),
    ])

    class Meta:
        db_table = "car"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["type"]),
        ]


class Manufacturer(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    country = models.CharField(max_length=255)

    class Meta:
        db_table = "manufacturer"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["country"]),
        ]


# 新增一个表用于记录哪些模型，已经被写入数据了
class InitialModels(models.Model):
    model_name = models.CharField(max_length=255, unique=True)
    model_data = models.JSONField()

    class Meta:
        db_table = "initial_models"
        indexes = [
            models.Index(fields=["model_name"]),
        ]
