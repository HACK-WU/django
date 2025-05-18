import asyncio
import logging
import types

from asgiref.sync import async_to_sync, iscoroutinefunction, sync_to_async

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
from django.core.signals import request_finished
from django.db import connections, transaction
from django.urls import get_resolver, set_urlconf
from django.utils.log import log_response
from django.utils.module_loading import import_string

from .exception import convert_exception_to_response

logger = logging.getLogger("django.request")


class BaseHandler:
    # _view_middleware (list)
    # 存储视图中间件的process_view方法
    # 在视图函数执行前按注册顺序依次调用,如果返回Response对象，则不会执行视图函数
    # 用于实现请求拦截（如权限验证）、请求预处理等功能
    # 示例：CsrfViewMiddleware.process_view用于CSRF防护
    _view_middleware = None
    # _template_response_middleware (list)
    # 存储模板响应中间件的process_template_response方法
    # 在模板响应渲染前按注册顺序调用
    # 用于修改模板响应对象（如设置缓存头、添加响应内容）
    _template_response_middleware = None
    # _exception_middleware (list)
    # 存储异常处理中间件的process_exception方法
    # 在视图处理抛出异常时按注册顺序调用，任意一个返回response则终止调用
    # 用于全局异常捕获和错误响应生成
    _exception_middleware = None
    # 执行视图函数时调用的中间件
    _middleware_chain = None

    def load_middleware(self, is_async=False):
        """
        为当前实例加载并配置中间件链。

        该方法从settings.MIDDLEWARE导入中间件类并按正确顺序初始化，
        将中间件的process_view、process_template_response、process_exception
        方法分别注册到对应的处理列表中。

        参数:
            is_async (bool): 指示是否使用异步请求处理模式。当为True时，
                             使用_async版本的get_response方法。

        必须在环境配置完成后调用(参见子类的__call__方法)。
        返回:
            None
        """
        self._view_middleware = []
        self._template_response_middleware = []
        self._exception_middleware = []

        get_response = self._get_response_async if is_async else self._get_response
        # 获取到request请求处理器：handler; response=handler(request)
        handler = convert_exception_to_response(get_response)
        handler_is_async = is_async

        # 处理中间件链的构建，按settings.MIDDLEWARE的逆序进行封装
        for middleware_path in reversed(settings.MIDDLEWARE):
            middleware = import_string(middleware_path)
            middleware_can_sync = getattr(middleware, "sync_capable", True)
            middleware_can_async = getattr(middleware, "async_capable", False)

            # 验证中间件必须具备至少一种处理模式能力
            if not middleware_can_sync and not middleware_can_async:
                raise RuntimeError(
                    "Middleware %s must have at least one of "
                    "sync_capable/async_capable set to True." % middleware_path
                )

            # 确定当前中间件的处理模式
            elif not handler_is_async and middleware_can_sync:
                middleware_is_async = False
            else:
                middleware_is_async = middleware_can_async

            # 实例化中间件并处理可能的MiddlewareNotUsed异常
            try:
                # Adapt handler, if needed.
                adapted_handler = self.adapt_method_mode(
                    middleware_is_async,
                    handler,
                    handler_is_async,
                    debug=settings.DEBUG,
                    name="middleware %s" % middleware_path,
                )
                # 被中间件包装过后的对象，
                # 被调用时会先执行process_request方法，
                # 然后执行get_response
                # 最后执行process_response方法
                mw_instance = middleware(adapted_handler)
            except MiddlewareNotUsed as exc:
                if settings.DEBUG:
                    if str(exc):
                        logger.debug("MiddlewareNotUsed(%r): %s", middleware_path, exc)
                    else:
                        logger.debug("MiddlewareNotUsed: %r", middleware_path)
                continue
            else:
                handler = adapted_handler

            if mw_instance is None:
                raise ImproperlyConfigured(
                    "Middleware factory %s returned None." % middleware_path
                )

            # 注册中间件的视图处理方法
            if hasattr(mw_instance, "process_view"):
                self._view_middleware.insert(
                    0,
                    self.adapt_method_mode(is_async, mw_instance.process_view),
                )

            # 注册中间件的模板响应处理方法
            if hasattr(mw_instance, "process_template_response"):
                self._template_response_middleware.append(
                    self.adapt_method_mode(
                        is_async, mw_instance.process_template_response
                    ),
                )

            # 注册中间件的异常处理方法（始终使用同步模式）
            if hasattr(mw_instance, "process_exception"):
                self._exception_middleware.append(
                    self.adapt_method_mode(False, mw_instance.process_exception),
                )

            # 将当前中间件包装为新的处理器
            handler = convert_exception_to_response(mw_instance)
            handler_is_async = middleware_is_async

        # 完成中间件链顶层处理器的适配并保存到实例
        handler = self.adapt_method_mode(is_async, handler, handler_is_async)
        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        # 此时_middleware_chain 就是用于处理request请求的处理器
        # _get_response方法已经被包装在里面了
        self._middleware_chain = handler

    def adapt_method_mode(
        self,
        is_async,
        method,
        method_is_async=None,
        debug=False,
        name=None,
    ):
        """
        适配方法以匹配指定的同步/异步模式。

        参数:
            is_async (bool): 目标模式标志，True表示需要异步模式，False表示同步模式
            method (callable): 需要适配的目标方法
            method_is_async (bool, optional): 显式指定方法是否为异步函数，默认自动检测
            debug (bool, optional): 是否启用调试日志输出
            name (str, optional): 方法的标识名称，用于调试日志

        返回值:
            callable: 适配后的包装方法或原始方法本身
            - 当需要转换模式时返回包装器
            - 当模式匹配时直接返回原始方法
        """
        # 自动检测方法是否为异步函数
        if method_is_async is None:
            method_is_async = iscoroutinefunction(method)

        # 调试模式下生成默认方法名称
        if debug and not name:
            name = name or "method %s()" % method.__qualname__

        # 根据目标模式进行适配处理
        if is_async:
            # 异步模式下需要将同步方法包装为异步
            if not method_is_async:
                if debug:
                    logger.debug("Synchronous handler adapted for %s.", name)
                return sync_to_async(method, thread_sensitive=True)
        elif method_is_async:
            # 同步模式下需要将异步方法包装为同步
            if debug:
                logger.debug("Asynchronous handler adapted for %s.", name)
            return async_to_sync(method)

        # 默认返回原始方法
        return method

    def get_response(self, request):
        """Return an HttpResponse object for the given HttpRequest."""
        # Setup default url resolver for this thread
        set_urlconf(settings.ROOT_URLCONF)
        response = self._middleware_chain(request)
        response._resource_closers.append(request.close)
        if response.status_code >= 400:
            log_response(
                "%s: %s",
                response.reason_phrase,
                request.path,
                response=response,
                request=request,
            )
        return response

    async def get_response_async(self, request):
        """
        Asynchronous version of get_response.

        Funneling everything, including WSGI, into a single async
        get_response() is too slow. Avoid the context switch by using
        a separate async response path.
        """
        # Setup default url resolver for this thread.
        set_urlconf(settings.ROOT_URLCONF)
        response = await self._middleware_chain(request)
        response._resource_closers.append(request.close)
        if response.status_code >= 400:
            await sync_to_async(log_response, thread_sensitive=False)(
                "%s: %s",
                response.reason_phrase,
                request.path,
                response=response,
                request=request,
            )
        return response

    def _get_response(self, request):
        """
        Resolve and call the view, then apply view, exception, and
        template_response middleware. This method is everything that happens
        inside the request/response middleware.

        参数:
            request: 请求对象，包含客户端发送的HTTP请求信息
                     (如方法、路径、头部、正文等)

        返回值:
            response: 响应对象，处理完成后返回给客户端的HTTP响应
                     若中间件或视图未返回响应，可能为None
        """
        response = None
        # 解析请求获取视图函数及其参数
        # 包含URL路由解析和参数捕获过程
        # callback: 视图函数
        # callback_args: 视图函数参数列表
        # callback_kwargs: 视图函数参数字典
        callback, callback_args, callback_kwargs = self.resolve_request(request)

        # 应用视图中间件链处理流程
        # 按注册顺序依次调用中间件方法，任一中间件返回响应则终止后续处理
        for middleware_method in self._view_middleware:
            response = middleware_method(
                request, callback, callback_args, callback_kwargs
            )
            if response:
                break

        # 视图执行核心逻辑处理
        # 1. 包装视图为原子操作以支持事务控制
        # 2. 处理异步视图的同步化适配
        # 3. 异常捕获与中间件异常处理链传递
        if response is None:
            wrapped_callback = self.make_view_atomic(callback)
            # 如果是异步视图，需要在子线程中执行
            if iscoroutinefunction(wrapped_callback):
                wrapped_callback = async_to_sync(wrapped_callback)
            try:
                response = wrapped_callback(request, *callback_args, **callback_kwargs)
            except Exception as e:
                response = self.process_exception_by_middleware(e, request)
                if response is None:
                    raise

        # 响应有效性验证
        # 检查视图或中间件是否返回合法响应对象
        # 第二个参数用于定位返回None的具体调用方
        self.check_response(response, callback)

        # 模板响应处理流程
        # 1. 判断响应是否支持延迟渲染（具有render方法）
        # 2. 应用模板响应中间件链处理
        # 3. 执行最终的模板渲染操作
        # 4. 渲染阶段的异常处理
        if hasattr(response, "render") and callable(response.render):
            # 模板响应中间件应用阶段
            # 每个中间件必须返回响应对象，否则视为编程错误
            for middleware_method in self._template_response_middleware:
                response = middleware_method(request, response)
                # 验证中间件返回值有效性
                # name参数用于生成更精确的错误定位信息
                self.check_response(
                    response,
                    middleware_method,
                    name="%s.process_template_response"
                    % (middleware_method.__self__.__class__.__name__,),
                )

            # 执行最终渲染操作
            # 渲染阶段异常需再次经过异常中间件处理
            try:
                response = response.render()
            except Exception as e:
                response = self.process_exception_by_middleware(e, request)
                if response is None:
                    raise

        return response

    async def _get_response_async(self, request):
        """
        Resolve and call the view, then apply view, exception, and
        template_response middleware. This method is everything that happens
        inside the request/response middleware.
        """
        response = None
        callback, callback_args, callback_kwargs = self.resolve_request(request)

        # Apply view middleware.
        for middleware_method in self._view_middleware:
            response = await middleware_method(
                request, callback, callback_args, callback_kwargs
            )
            if response:
                break

        if response is None:
            wrapped_callback = self.make_view_atomic(callback)
            # If it is a synchronous view, run it in a subthread
            if not iscoroutinefunction(wrapped_callback):
                wrapped_callback = sync_to_async(
                    wrapped_callback, thread_sensitive=True
                )
            try:
                response = await wrapped_callback(
                    request, *callback_args, **callback_kwargs
                )
            except Exception as e:
                response = await sync_to_async(
                    self.process_exception_by_middleware,
                    thread_sensitive=True,
                )(e, request)
                if response is None:
                    raise

        # Complain if the view returned None or an uncalled coroutine.
        self.check_response(response, callback)

        # If the response supports deferred rendering, apply template
        # response middleware and then render the response
        if hasattr(response, "render") and callable(response.render):
            for middleware_method in self._template_response_middleware:
                response = await middleware_method(request, response)
                # Complain if the template response middleware returned None or
                # an uncalled coroutine.
                self.check_response(
                    response,
                    middleware_method,
                    name="%s.process_template_response"
                    % (middleware_method.__self__.__class__.__name__,),
                )
            try:
                if iscoroutinefunction(response.render):
                    response = await response.render()
                else:
                    response = await sync_to_async(
                        response.render, thread_sensitive=True
                    )()
            except Exception as e:
                response = await sync_to_async(
                    self.process_exception_by_middleware,
                    thread_sensitive=True,
                )(e, request)
                if response is None:
                    raise

        # Make sure the response is not a coroutine
        if asyncio.iscoroutine(response):
            raise RuntimeError("Response is still a coroutine.")
        return response

    def resolve_request(self, request):
        """
        Retrieve/set the urlconf for the request. Return the view resolved,
        with its args and kwargs.
        """
        # Work out the resolver.
        if hasattr(request, "urlconf"):
            urlconf = request.urlconf
            set_urlconf(urlconf)
            resolver = get_resolver(urlconf)
        else:
            resolver = get_resolver()
        # Resolve the view, and assign the match object back to the request.
        resolver_match = resolver.resolve(request.path_info)
        request.resolver_match = resolver_match
        return resolver_match

    def check_response(self, response, callback, name=None):
        """
        Raise an error if the view returned None or an uncalled coroutine.
        """
        if not (response is None or asyncio.iscoroutine(response)):
            return
        if not name:
            if isinstance(callback, types.FunctionType):  # FBV
                name = "The view %s.%s" % (callback.__module__, callback.__name__)
            else:  # CBV
                name = "The view %s.%s.__call__" % (
                    callback.__module__,
                    callback.__class__.__name__,
                )
        if response is None:
            raise ValueError(
                "%s didn't return an HttpResponse object. It returned None "
                "instead." % name
            )
        elif asyncio.iscoroutine(response):
            raise ValueError(
                "%s didn't return an HttpResponse object. It returned an "
                "unawaited coroutine instead. You may need to add an 'await' "
                "into your view." % name
            )

    # Other utility methods.

    def make_view_atomic(self, view):
        non_atomic_requests = getattr(view, "_non_atomic_requests", set())
        for alias, settings_dict in connections.settings.items():
            if settings_dict["ATOMIC_REQUESTS"] and alias not in non_atomic_requests:
                if iscoroutinefunction(view):
                    raise RuntimeError(
                        "You cannot use ATOMIC_REQUESTS with async views."
                    )
                view = transaction.atomic(using=alias)(view)
        return view

    def process_exception_by_middleware(self, exception, request):
        """
        Pass the exception to the exception middleware. If no middleware
        return a response for this exception, return None.
        """
        for middleware_method in self._exception_middleware:
            response = middleware_method(request, exception)
            if response:
                return response
        return None


def reset_urlconf(sender, **kwargs):
    """Reset the URLconf after each request is finished."""
    set_urlconf(None)


request_finished.connect(reset_urlconf)
