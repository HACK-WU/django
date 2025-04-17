from django.db import models

# https://django-elasticsearch-dsl.readthedocs.io/en/latest/quickstart.html
class Car(models.Model):
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=255)
    description = models.TextField()
    type = models.IntegerField(choices=[
        (1, "Sedan"),
        (2, "Truck"),
        (4, "SUV"),
    ])
