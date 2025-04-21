# coding=utf-8
# Time: 2025/4/20 19:55
# name: query_stark
# author: HACK-WU

import hello
from example.django_es_dsl.document import CarDocument

s = CarDocument.search().filter("term", color="red")

for hit in s:
    print("Car name : {}, color {}".format(hit.name, hit.color))

# Car name : Audi, color red
# Car name : Ferrari, color red

s = CarDocument.search().query("match", description="manufacturer")

for hit in s:
    print("Car name : {}, manufacturer {}".format(hit.name, hit.color))

# Car name : Audi, manufacturer red
# Car name : BMW, manufacturer blue
# Car name : Porsche, manufacturer yellow
# Car name : Ferrari, manufacturer red
# Car name : Mercedes-Benz, manufacturer black

# 将 elastisearch 的结果转换为真正的 django 查询集
for q in s.to_queryset()[0:2]:
    print(q, type(q))

# Car object (18) <class 'app01.models.Car'>
# Car object (19) <class 'app01.models.Car'>
