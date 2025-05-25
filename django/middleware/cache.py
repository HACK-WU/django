"""
Cache middleware. If enabled, each Django-powered page will be cached based on
URL. The canonical way to enable cache middleware is to set
``UpdateCacheMiddleware`` as your first piece of middleware, and
``FetchFromCacheMiddleware`` as the last::

    MIDDLEWARE = [
        'django.middleware.cache.UpdateCacheMiddleware',
        ...
        'django.middleware.cache.FetchFromCacheMiddleware'
    ]

This is counterintuitive, but correct: ``UpdateCacheMiddleware`` needs to run
last during the response phase, which processes middleware bottom-up;
``FetchFromCacheMiddleware`` needs to run last during the request phase, which
processes middleware top-down.

The single-class ``CacheMiddleware`` can be used for some simple sites.
However, if any other piece of middleware needs to affect the cache key, you'll
need to use the two-part ``UpdateCacheMiddleware`` and
``FetchFromCacheMiddleware``. This'll most often happen when you're using
Django's ``LocaleMiddleware``.

More details about how the caching works:

* Only GET or HEAD-requests with status code 200 are cached.

* The number of seconds each page is stored for is set by the "max-age" section
  of the response's "Cache-Control" header, falling back to the
  CACHE_MIDDLEWARE_SECONDS setting if the section was not found.

* This middleware expects that a HEAD request is answered with the same response
  headers exactly like the corresponding GET request.

* When a hit occurs, a shallow copy of the original response object is returned
  from process_request.

* Pages will be cached based on the contents of the request headers listed in
  the response's "Vary" header.

* This middleware also sets ETag, Last-Modified, Expires and Cache-Control
  headers on the response object.

"""

import time

from django.conf import settings
from django.core.cache import DEFAULT_CACHE_ALIAS, caches
from django.utils.cache import (
    get_cache_key,
    get_max_age,
    has_vary_header,
    learn_cache_key,
    patch_response_headers,
)
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import parse_http_date_safe


class UpdateCacheMiddleware(MiddlewareMixin):
    """
    响应阶段缓存更新中间件，用于在响应可缓存时更新缓存。

    必须与FetchFromCacheMiddleware配合使用，构成完整的缓存更新/读取机制。
    该中间件需要放置在MIDDLEWARE列表最前端，确保响应阶段最后执行。

    属性:
        cache_timeout: 全局默认缓存超时时间（秒），来自CACHE_MIDDLEWARE_SECONDS配置
        page_timeout: 页面级缓存超时时间（优先级高于全局配置）
        key_prefix: 缓存键前缀，用于命名空间隔离
        cache_alias: 缓存配置别名，指定使用的缓存后端
    """

    def __init__(self, get_response):
        """
        初始化中间件实例

        参数:
            get_response: 下一中间件或视图的可调用对象
        """
        super().__init__(get_response)
        self.cache_timeout = settings.CACHE_MIDDLEWARE_SECONDS
        self.page_timeout = None
        self.key_prefix = settings.CACHE_MIDDLEWARE_KEY_PREFIX
        self.cache_alias = settings.CACHE_MIDDLEWARE_ALIAS

    @property
    def cache(self):
        """
        获取配置的缓存后端实例

        返回:
            caches[self.cache_alias]: 指定别名的缓存后端对象
        """
        return caches[self.cache_alias]

    def _should_update_cache(self, request, response):
        """
        判断当前请求-响应周期是否需要更新缓存

        参数:
            request: HttpRequest对象
            response: HttpResponse对象

        返回:
            bool: 当且仅当request带有_cache_update_cache标记且为True时返回True
        """
        return hasattr(request, "_cache_update_cache") and request._cache_update_cache

    def process_response(self, request, response):
        """
        响应处理主逻辑：执行缓存更新决策和实际缓存操作

        参数:
            request: HttpRequest对象，包含请求上下文信息
            response: HttpResponse对象，待处理的响应数据

        返回:
            HttpResponse对象：可能被缓存或原样返回的响应

        处理流程包含：
        1. 快速路径排除：非缓存更新标记、流式响应、非成功状态码
        2. 安全防护：防止缓存包含敏感Cookie的响应
        3. 缓存策略解析：优先级为page_timeout > Cache-Control > 全局配置
        4. 响应头增强：添加缓存相关HTTP头信息
        5. 异步缓存：支持模板渲染后缓存（通过post_render_callback）
        """
        if not self._should_update_cache(request, response):
            # 跳过缓存更新流程
            return response

        # 排除流式响应和非成功状态码响应（仅保留200/304）
        if response.streaming or response.status_code not in (200, 304):
            return response

        # 防止缓存包含用户敏感信息的响应：
        # 当请求无Cookie但响应设置了Cookie且Vary: Cookie存在时拒绝缓存
        if (
            not request.COOKIES
            and response.cookies
            and has_vary_header(response, "Cookie")
        ):
            return response

        # 尊重响应的Cache-Control: private指令
        if "private" in response.get("Cache-Control", ()):
            return response

        # 确定缓存超时时间（优先级：页面级 > Cache-Control > 全局配置）
        timeout = self.page_timeout
        if timeout is None:
            timeout = get_max_age(response)
            if timeout is None:
                timeout = self.cache_timeout
            elif timeout == 0:
                # 显式禁用缓存（max-age=0）
                return response

        # 在响应头中添加缓存控制信息
        patch_response_headers(response, timeout)

        # 执行实际缓存操作（支持模板延迟渲染场景）
        if timeout and response.status_code == 200:
            cache_key = learn_cache_key(
                request, response, timeout, self.key_prefix, cache=self.cache
            )
            if hasattr(response, "render") and callable(response.render):
                # 延迟渲染场景：注册回调函数
                response.add_post_render_callback(
                    lambda r: self.cache.set(cache_key, r, timeout)
                )
            else:
                # 即时缓存响应内容
                self.cache.set(cache_key, response, timeout)

        return response



class FetchFromCacheMiddleware(MiddlewareMixin):
    """
    Request-phase缓存中间件，用于从缓存中获取页面内容。

    必须作为双组件更新/获取缓存中间件的一部分使用。
    FetchFromCacheMiddleware必须位于MIDDLEWARE列表的最后位置，
    确保在请求阶段最后一个被调用。

    参数:
        get_response: 可调用对象，指向中间件链的下一个处理节点

    属性:
        key_prefix: 缓存键前缀字符串（来自CACHE_MIDDLEWARE_KEY_PREFIX配置）
        cache_alias: 缓存实例别名（来自CACHE_MIDDLEWARE_ALIAS配置）

    执行流程:
        1. 初始化时绑定缓存配置参数
        2. 通过property动态获取缓存实例
        3. 请求阶段尝试从缓存获取响应
        4. 根据请求方法和缓存状态决定是否更新缓存
    """

    def __init__(self, get_response):
        """
        初始化中间件实例

        参数:
            get_response: WSGI应用的下一个处理节点
        """
        super().__init__(get_response)
        self.key_prefix = settings.CACHE_MIDDLEWARE_KEY_PREFIX
        self.cache_alias = settings.CACHE_MIDDLEWARE_ALIAS

    @property
    def cache(self):
        """
        获取配置的缓存后端实例

        返回值:
            指定缓存别名对应的缓存操作对象
        """
        return caches[self.cache_alias]

    def process_request(self, request):
        """
        处理请求阶段的缓存获取逻辑

        参数:
            request: HttpRequest对象，包含请求元数据和状态信息

        返回值:
            None表示继续中间件链处理
            HttpResponse对象表示直接返回缓存响应

        缓存处理流程:
            1. 非GET/HEAD请求直接跳过缓存检查
            2. 构建并验证GET请求的缓存键
            3. 当GET缓存未命中时尝试HEAD请求的缓存
            4. 计算缓存响应的Age头信息
            5. 返回有效缓存或触发重建流程
        """
        if request.method not in ("GET", "HEAD"):
            request._cache_update_cache = False
            return None  # 非幂等请求不检查缓存

        # 构建GET请求的缓存键并尝试获取响应
        cache_key = get_cache_key(request, self.key_prefix, "GET", cache=self.cache)
        if cache_key is None:
            request._cache_update_cache = True
            return None  # 无法生成有效缓存键，标记需重建

        response = self.cache.get(cache_key)
        # 当GET缓存未命中且为HEAD请求时，尝试获取HEAD专用缓存
        if response is None and request.method == "HEAD":
            cache_key = get_cache_key(
                request, self.key_prefix, "HEAD", cache=self.cache
            )
            response = self.cache.get(cache_key)

        if response is None:
            request._cache_update_cache = True
            return None  # 完全未命中，标记需重建

        # 计算并设置缓存响应的Age头信息
        if (max_age_seconds := get_max_age(response)) is not None and (
            expires_timestamp := parse_http_date_safe(response["Expires"])
        ) is not None:
            now_timestamp = int(time.time())
            remaining_seconds = expires_timestamp - now_timestamp
            # 使用Age: 0防止时钟回拨导致负值
            response["Age"] = max(0, max_age_seconds - remaining_seconds)

        # 缓存命中处理
        request._cache_update_cache = False
        return response


class CacheMiddleware(UpdateCacheMiddleware, FetchFromCacheMiddleware):
    """
    缓存中间件基类，为简单站点提供基础缓存行为实现

    继承关系：
        UpdateCacheMiddleware - 提供缓存更新功能
        FetchFromCacheMiddleware - 提供缓存读取功能

    该中间件同时作为缓存装饰器的钩子点，通过中间件装饰器工具生成
    装饰器实例时会使用此类作为核心处理逻辑
    """

    def __init__(self, get_response, cache_timeout=None, page_timeout=None, **kwargs):
        """
        初始化缓存中间件实例

        参数:
            get_response: 下一个中间件或视图处理函数
            cache_timeout: 全局缓存超时时间（秒），若为None则使用系统默认值
            page_timeout: 页面级缓存超时时间（秒），用于覆盖全局设置
            **kwargs: 扩展参数包含：
                key_prefix: 缓存键前缀（字符串或None）
                cache_alias: 缓存配置别名（字符串或None）

        处理逻辑：
            1. 参数优先级：显式传入值 > 中间件默认值 > 系统默认值
            2. key_prefix处理空字符串兼容性
            3. cache_alias默认回退到DEFAULT_CACHE_ALIAS
        """
        super().__init__(get_response)
        # 处理缓存键前缀参数逻辑
        # 区分"使用默认值"和"参数未提供"两种情况
        try:
            key_prefix = kwargs["key_prefix"]
            if key_prefix is None:
                key_prefix = ""
            self.key_prefix = key_prefix
        except KeyError:
            pass

        # 处理缓存别名参数逻辑
        # 支持显式设置None触发默认别名回退
        try:
            cache_alias = kwargs["cache_alias"]
            if cache_alias is None:
                cache_alias = DEFAULT_CACHE_ALIAS
            self.cache_alias = cache_alias
        except KeyError:
            pass

        # 处理缓存超时时间参数
        # cache_timeout优先级高于系统默认值
        if cache_timeout is not None:
            self.cache_timeout = cache_timeout
        self.page_timeout = page_timeout

