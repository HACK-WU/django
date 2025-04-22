from app01 import ser
from app01.utils import initial_data

READY_INITIAL_DATA = False

cars_info = [
    {
        "id": 1,
        "name": "Audi",
        "color": "red",
        "description": "Audi is a German car manufacturer.",
        "type": 1,
        "manufacturer": 1,
    },
    {
        "id": 2,
        "name": "BMW",
        "color": "blue",
        "description": "BMW is a German car manufacturer.",
        "type": 1,
        "manufacturer": 2,
    },
    {
        "id": 3,
        "name": "Mercedes-Benz",
        "color": "black",
        "description": "Mercedes-Benz is a German car manufacturer.",
        "type": 1,
        "manufacturer": 3,
    },
    {
        "id": 4,
        "name": "Porsche",
        "color": "yellow",
        "description": "Porsche is a German car manufacturer.",
        "type": 1,
        "manufacturer": 4,
    },
    {
        "id": 5,
        "name": "Ferrari",
        "color": "red",
        "description": "Ferrari is a German car manufacturer.",
        "type": 1,
        "manufacturer": 5,
    },
]

manufacturer_infos = [
    {
        "id": 1,
        "name": "Audi",
        "country": "Germany",
    },
    {
        "id": 2,
        "name": "BMW",
        "country": "Germany",
    },
    {
        "id": 3,
        "name": "Mercedes-Benz",
        "country": "Germany",
    },
    {
        "id": 4,
        "name": "Porsche",
        "country": "Germany",
    },
    {
        "id": 5,
        "name": "Ferrari",
        "country": "Italy",
    },
]

ad_infos = [
    {
        "id": 1,
        "title": "Audi A4",
        "description": "Audi A4 is a German car.",
        "url": "https://www.audi.com/",
        "car": 1,
    },
    {
        "id": 2,
        "title": "BMW 5 Series",
        "description": "BMW 5 Series is a German car.",
        "url": "https://www.bmw.com/",
        "car": 2,
    },
    {
        "id": 3,
        "title": "Mercedes-Benz C-Class",
        "description": "Mercedes-Benz C-Class is a German car.",
        "url": "https://www.mercedes-benz.com/",
        "car": 3,
    },
    {
        "id": 4,
        "title": "Porsche 911",
        "description": "Porsche 911 is a German car.",
        "url": "https://www.porsche.com/",
        "car": 4,
    },
    {
        "id": 5,
        "title": "Ferrari 488",
        "description": "Ferrari 488 is an Italian car.",
        "url": "https://www.ferrari.com/",
        "car": 5,
    },
]

serializer_instance = [
    ser.ManufacturerSerializer(data=manufacturer_infos, many=True),
    ser.CarSerializer(data=cars_info, many=True),
    ser.AdSerializer(data=ad_infos, many=True),
]


def initial_models():
    # 如歌数据库cars记录数量小于，则批量创建
    # python manage.py rebuild_es 该命令可以完成创建并写入es数据中
    for i in serializer_instance:
        initial_data(i)
    global ready_initial_data
    ready_initial_data = True
