from demo.settings import *

INSTALLED_APPS += [
    'app01',
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "django_demo",
        "USER": "root",
        "PASSWORD": "123456",
        "HOST": "127.0.0.1",
        "PORT": "3306",
    }
}

# mysql create database
# CREATE DATABASE `django_demo` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;
