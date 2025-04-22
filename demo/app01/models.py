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
    manufacturer = models.ForeignKey("Manufacturer", related_name="cars",null=True,
                                     db_constraint=False,
                                     on_delete=models.DO_NOTHING)

    # https://django-elasticsearch-dsl.readthedocs.io/en/latest/fields.html
    def type_to_string(self):
        """Convert the type field to its string representation
        (the boneheaded way).
        """
        if self.type == 1:
            return "Sedan"
        elif self.type == 2:
            return "Truck"
        else:
            return "SUV"

    class Meta:
        db_table = "car"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["type"]),
        ]


class Manufacturer(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    country = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "manufacturer"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["country"]),
        ]


class Ad(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    url = models.URLField()
    car = models.ForeignKey('Car', related_name='ads', db_constraint=False,null=True,
                            on_delete=models.DO_NOTHING)

    class Meta:
        db_table = "ad"


# 新增一个表用于记录哪些模型，已经被写入数据了
class InitialModels(models.Model):
    model_name = models.CharField(max_length=255, unique=True)
    model_data = models.JSONField()

    class Meta:
        db_table = "initial_models"
        indexes = [
            models.Index(fields=["model_name"]),
        ]
