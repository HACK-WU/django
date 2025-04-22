# coding=utf-8
# Time: 2025/4/18 22:43
# name: shell
# author: HACK-WU

#
import hello
from app01.ser import ManufacturerSerializer

data={
    # "id": 1,
    "name": "Audi1",
    "country": "Germany",
}

ser = ManufacturerSerializer(data=data)
ser.is_valid(raise_exception=True)
ser.save()
