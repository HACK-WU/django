# coding=utf-8
# Time: 2025/4/18 22:44
# name: hello
# author: HACK-WU


import os
import django
import dotenv

dotenv.load_dotenv()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

django.setup()
