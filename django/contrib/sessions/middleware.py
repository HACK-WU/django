import time
from importlib import import_module

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import http_date


class SessionMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        """
        初始化会话中间件

        参数:
            get_response: 下一个中间件或视图函数的可调用对象
            settings.SESSION_ENGINE: 会话存储引擎的模块路径字符串
            engine: 动态导入的会话引擎模块
            self.SessionStore: 会话存储类引用
        """
        super().__init__(get_response)
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore

    def process_request(self, request):
        """
        请求预处理阶段绑定会话对象

        参数:
            request: HttpRequest对象，包含请求元数据和COOKIES信息
            settings.SESSION_COOKIE_NAME: 会话cookie名称配置

        执行流程:
        1. 从请求cookie中提取会话密钥
        2. 使用SessionStore创建会话对象
        3. 将会话对象绑定到request.session属性
        """
        session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        request.session = self.SessionStore(session_key)

    def process_response(self, request, response):
        """
        响应后处理阶段管理会话状态持久化

        参数:
            request: 已处理的HttpRequest对象
            response: HttpResponse对象，可能被修改的响应
            settings.SESSION_COOKIE_*: 各种会话cookie配置参数

        返回值:
            处理后的HttpResponse对象，可能包含：
            - 新的Set-Cookie头
            - 删除Cookie的Set-Cookie头
            - 未修改的原始响应

        执行流程:
        1. 检查会话属性是否存在（防止未初始化情况）
        2. 判断会话是否为空并需要删除cookie
        3. 处理需要保留的会话：
           - 添加Vary: Cookie头
           - 条件性保存会话数据
           - 设置新的cookie过期时间
        """
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response

        # 处理会话cookie删除逻辑
        # 当且仅当cookie存在且会话为空时触发删除
        if settings.SESSION_COOKIE_NAME in request.COOKIES and empty:
            response.delete_cookie(
                settings.SESSION_COOKIE_NAME,
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            patch_vary_headers(response, ("Cookie",))

        else:
            # 处理会话cookie保留逻辑
            if accessed:
                patch_vary_headers(response, ("Cookie",))

            # 条件性保存会话数据并设置cookie
            if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
                if request.session.get_expire_at_browser_close():
                    max_age = None
                    expires = None
                else:
                    max_age = request.session.get_expiry_age()
                    expires_time = time.time() + max_age
                    expires = http_date(expires_time)

                # 避免服务器错误响应时保存会话
                if response.status_code < 500:
                    try:
                        request.session.save()
                    except UpdateError:
                        raise SessionInterrupted(
                            "The request's session was deleted before the "
                            "request completed. The user may have logged "
                            "out in a concurrent request, for example."
                        )

                    response.set_cookie(
                        settings.SESSION_COOKIE_NAME,
                        request.session.session_key,
                        max_age=max_age,
                        expires=expires,
                        domain=settings.SESSION_COOKIE_DOMAIN,
                        path=settings.SESSION_COOKIE_PATH,
                        secure=settings.SESSION_COOKIE_SECURE or None,
                        httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                        samesite=settings.SESSION_COOKIE_SAMESITE,
                    )

        return response
