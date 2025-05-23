import re

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.utils.deprecation import MiddlewareMixin


class SecurityMiddleware(MiddlewareMixin):
    def __init__(self, get_response):
        """
        初始化安全中间件的配置参数

        参数:
            get_response: 可调用对象，用于获取后续中间件或视图的响应

        该方法初始化以下安全相关配置属性:
        - HSTS配置: sts_seconds, sts_include_subdomains, sts_preload
        - 内容类型防护: content_type_nosniff
        - SSL重定向配置: redirect, redirect_host, redirect_exempt
        - 引用策略: referrer_policy
        - 跨域 opener 策略: cross_origin_opener_policy

        所有配置值均从Django settings模块中获取，并转换为中间件实例属性
        """
        super().__init__(get_response)
        self.sts_seconds = settings.SECURE_HSTS_SECONDS
        self.sts_include_subdomains = settings.SECURE_HSTS_INCLUDE_SUBDOMAINS
        self.sts_preload = settings.SECURE_HSTS_PRELOAD
        self.content_type_nosniff = settings.SECURE_CONTENT_TYPE_NOSNIFF
        self.redirect = settings.SECURE_SSL_REDIRECT
        self.redirect_host = settings.SECURE_SSL_HOST
        self.redirect_exempt = [re.compile(r) for r in settings.SECURE_REDIRECT_EXEMPT]
        self.referrer_policy = settings.SECURE_REFERRER_POLICY
        self.cross_origin_opener_policy = settings.SECURE_CROSS_ORIGIN_OPENER_POLICY

    def process_request(self, request):
        """
        处理请求阶段的SSL重定向逻辑

        参数:
            request: HttpRequest对象，包含请求路径和协议信息

        返回值:
            None表示继续中间件链处理
            HttpResponsePermanentRedirect对象表示返回301重定向响应

        执行流程:
        1. 移除请求路径左侧的斜杠
        2. 检查是否启用SSL重定向且请求非安全连接
        3. 排除匹配SECURE_REDIRECT_EXEMPT规则的路径
        4. 构造HTTPS安全链接并返回重定向响应
        """
        path = request.path.lstrip("/")
        if (
            self.redirect
            and not request.is_secure()
            and not any(pattern.search(path) for pattern in self.redirect_exempt)
        ):
            host = self.redirect_host or request.get_host()
            return HttpResponsePermanentRedirect(
                "https://%s%s" % (host, request.get_full_path())
            )

    def process_response(self, request, response):
        """
        处理响应阶段的安全头注入逻辑

        参数:
            request: HttpRequest对象，用于检查请求协议
            response: HttpResponse对象，用于添加安全头

        返回值:
            添加安全头后的HttpResponse对象

        执行步骤:
        1. HSTS头生成: 仅当启用且未被覆盖时添加
           - 构建max-age参数
           - 添加includeSubDomains和preload指令
        2. X-Content-Type-Options: 防止MIME类型嗅探
        3. Referrer-Policy: 支持字符串分割和可迭代对象处理
        4. Cross-Origin-Opener-Policy: 防御跨窗口攻击
        所有安全头仅在未设置的情况下添加默认值
        """
        if (
            self.sts_seconds
            and request.is_secure()
            and "Strict-Transport-Security" not in response
        ):
            sts_header = "max-age=%s" % self.sts_seconds
            if self.sts_include_subdomains:
                sts_header += "; includeSubDomains"
            if self.sts_preload:
                sts_header += "; preload"
            response.headers["Strict-Transport-Security"] = sts_header

        if self.content_type_nosniff:
            response.headers.setdefault("X-Content-Type-Options", "nosniff")

        if self.referrer_policy:
            # Support a comma-separated string or iterable of values to allow
            # fallback.
            response.headers.setdefault(
                "Referrer-Policy",
                ",".join(
                    [v.strip() for v in self.referrer_policy.split(",")]
                    if isinstance(self.referrer_policy, str)
                    else self.referrer_policy
                ),
            )

        if self.cross_origin_opener_policy:
            response.setdefault(
                "Cross-Origin-Opener-Policy",
                self.cross_origin_opener_policy,
            )
        return response
