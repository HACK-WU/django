from app01 import ser
from app01.models import *
from app01.utils import initial_data

READY_INITIAL_DATA = False

cars_info = [
    {
        "name": "Audi",
        "color": "red",
        "description": "Audi is a German car manufacturer.",
        "type": 1,
    },
    {
        "name": "BMW",
        "color": "blue",
        "description": "BMW is a German car manufacturer.",
        "type": 1,
    },
    {
        "name": "Mercedes-Benz",
        "color": "black",
        "description": "Mercedes-Benz is a German car manufacturer.",
        "type": 1,
    },
    {
        "name": "Porsche",
        "color": "yellow",
        "description": "Porsche is a German car manufacturer.",
        "type": 1,
    },
    {
        "name": "Ferrari",
        "color": "red",
        "description": "Ferrari is a German car manufacturer.",
        "type": 1,
    },
]

manufacturer_infos = [
    {
        "name": "Audi",
        "country": "Germany",
    },
    {
        "name": "BMW",
        "country": "Germany",
    },
    {
        "name": "Mercedes-Benz",
        "country": "Germany",
    },
    {
        "name": "Porsche",
        "country": "Germany",
    },
    {
        "name": "Ferrari",
        "country": "Italy",
    },
]

serializer_instance = [
    ser.CarSerializer(data=cars_info, many=True),
    ser.ManufacturerSerializer(data=manufacturer_infos, many=True),
]


def initial_models():
    # 如歌数据库cars记录数量小于，则批量创建
    # python manage.py rebuild_es 该命令可以完成创建并写入es数据中
    for i in serializer_instance:
        initial_data(i)
    global ready_initial_data
    ready_initial_data = True
