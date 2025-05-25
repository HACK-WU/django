"Functions that help with dynamically creating decorators for views."

from functools import partial, update_wrapper, wraps

from asgiref.sync import iscoroutinefunction, markcoroutinefunction


class classonlymethod(classmethod):
    def __get__(self, instance, cls=None):
        if instance is not None:
            raise AttributeError(
                "This method is available only on the class, not on instances."
            )
        return super().__get__(instance, cls)


def _update_method_wrapper(_wrapper, decorator):
    # _multi_decorate()'s bound_method isn't available in this scope. Cheat by
    # using it on a dummy function.
    @decorator
    def dummy(*args, **kwargs):
        pass

    update_wrapper(_wrapper, dummy)


def _multi_decorate(decorators, method):
    """
    Decorate `method` with one or more function decorators. `decorators` can be
    a single decorator or an iterable of decorators.
    """
    if hasattr(decorators, "__iter__"):
        # Apply a list/tuple of decorators if 'decorators' is one. Decorator
        # functions are applied so that the call order is the same as the
        # order in which they appear in the iterable.
        decorators = decorators[::-1]
    else:
        decorators = [decorators]

    def _wrapper(self, *args, **kwargs):
        # bound_method has the signature that 'decorator' expects i.e. no
        # 'self' argument, but it's a closure over self so it can call
        # 'func'. Also, wrap method.__get__() in a function because new
        # attributes can't be set on bound method objects, only on functions.
        bound_method = wraps(method)(partial(method.__get__(self, type(self))))
        for dec in decorators:
            bound_method = dec(bound_method)
        return bound_method(*args, **kwargs)

    # Copy any attributes that a decorator adds to the function it decorates.
    for dec in decorators:
        _update_method_wrapper(_wrapper, dec)
    # Preserve any existing attributes of 'method', including the name.
    update_wrapper(_wrapper, method)

    if iscoroutinefunction(method):
        markcoroutinefunction(_wrapper)

    return _wrapper


def method_decorator(decorator, name=""):
    """
    Convert a function decorator into a method decorator
    """

    # 'obj' can be a class or a function. If 'obj' is a function at the time it
    # is passed to _dec,  it will eventually be a method of the class it is
    # defined on. If 'obj' is a class, the 'name' is required to be the name
    # of the method that will be decorated.
    def _dec(obj):
        if not isinstance(obj, type):
            return _multi_decorate(decorator, obj)
        if not (name and hasattr(obj, name)):
            raise ValueError(
                "The keyword argument `name` must be the name of a method "
                "of the decorated class: %s. Got '%s' instead." % (obj, name)
            )
        method = getattr(obj, name)
        if not callable(method):
            raise TypeError(
                "Cannot decorate '%s' as it isn't a callable attribute of "
                "%s (%s)." % (name, obj, method)
            )
        _wrapper = _multi_decorate(decorator, method)
        setattr(obj, name, _wrapper)
        return obj

    # Don't worry about making _dec look similar to a list/tuple as it's rather
    # meaningless.
    if not hasattr(decorator, "__iter__"):
        update_wrapper(_dec, decorator)
    # Change the name to aid debugging.
    obj = decorator if hasattr(decorator, "__name__") else decorator.__class__
    _dec.__name__ = "method_decorator(%s)" % obj.__name__
    return _dec


def decorator_from_middleware_with_args(middleware_class):
    """
    创建带参数的中间件装饰器工厂函数

    参数:
        middleware_class: 中间件类对象，需实现__init__和__call__方法
            该类应接受请求处理函数和任意参数进行实例化

    返回值:
        function: 返回可调用对象装饰器，支持传入任意参数进行初始化
            生成的装饰器遵循标准中间件调用协议，可嵌套应用在视图函数上

    该函数实现中间件到装饰器的适配模式，典型应用场景：
    1. 需要传递配置参数给中间件的场景（如缓存超时时间）
    2. 需要动态创建不同配置的装饰器实例
    3. 统一中间件和装饰器编程范式

    使用示例:
        cache_page = decorator_from_middleware_with_args(CacheMiddleware)

        @cache_page(3600)  # 应用带参数的装饰器
        def my_view(request):
            pass
    """
    return make_middleware_decorator(middleware_class)


def decorator_from_middleware(middleware_class):
    """
    Given a middleware class (not an instance), return a view decorator. This
    lets you use middleware functionality on a per-view basis. The middleware
    is created with no params passed.
    """
    return make_middleware_decorator(middleware_class)()


def make_middleware_decorator(middleware_class):
    """
    创建中间件装饰器的工厂函数，将中间件类封装为视图装饰器

    参数:
        middleware_class: 中间件类对象，需实现标准中间件接口方法

    返回值:
        _make_decorator: 装饰器工厂函数，用于生成具体中间件装饰器
    """
    def _make_decorator(*m_args, **m_kwargs):
        """
        生成具体中间件装饰器的闭包函数

        参数:
            *m_args: 传递给中间件类的初始化位置参数
            **m_kwargs: 传递给中间件类的初始化关键字参数

        返回值:
            _decorator: 视图函数装饰器，用于封装中间件逻辑
        """
        def _decorator(view_func):
            """
            实际装饰视图函数的装饰器

            参数:
                view_func: 被装饰的视图函数

            返回值:
                _view_wrapper: 带中间件逻辑的视图包装函数
            """
            middleware = middleware_class(view_func, *m_args, **m_kwargs)

            def _pre_process_request(request, *args, **kwargs):
                """
                执行中间件的请求预处理和视图处理阶段

                参数:
                    request: HttpRequest对象
                    *args: 视图函数的位置参数
                    **kwargs: 视图函数的关键字参数

                返回值:
                    中间件处理结果（响应对象或None）

                处理流程：
                1. 执行process_request方法（若存在）
                2. 执行process_view方法（若存在）
                3. 任一阶段返回非None结果则终止流程
                """
                if hasattr(middleware, "process_request"):
                    result = middleware.process_request(request)
                    if result is not None:
                        return result
                if hasattr(middleware, "process_view"):
                    result = middleware.process_view(request, view_func, args, kwargs)
                    if result is not None:
                        return result
                return None

            def _process_exception(request, exception):
                """
                异常处理阶段的中间件逻辑

                参数:
                    request: HttpRequest对象
                    exception: 捕获的异常对象

                返回值:
                    中间件处理后的响应对象或重新抛出异常

                处理流程：
                1. 执行process_exception方法（若存在）
                2. 返回非None结果则终止异常处理流程
                """
                if hasattr(middleware, "process_exception"):
                    result = middleware.process_exception(request, exception)
                    if result is not None:
                        return result
                raise

            def _post_process_request(request, response):
                """
                响应后处理阶段的中间件逻辑

                参数:
                    request: HttpRequest对象
                    response: HttpResponse对象

                返回值:
                    处理后的响应对象

                处理流程：
                1. 处理模板响应（process_template_response）
                2. 延迟执行process_response直到模板渲染完成
                3. 非模板响应直接执行process_response
                """
                if hasattr(response, "render") and callable(response.render):
                    if hasattr(middleware, "process_template_response"):
                        response = middleware.process_template_response(
                            request, response
                        )
                    # Defer running of process_response until after the template
                    # has been rendered:
                    if hasattr(middleware, "process_response"):

                        def callback(response):
                            return middleware.process_response(request, response)

                        response.add_post_render_callback(callback)
                else:
                    if hasattr(middleware, "process_response"):
                        return middleware.process_response(request, response)
                return response

            if iscoroutinefunction(view_func):

                async def _view_wrapper(request, *args, **kwargs):
                    """
                    异步视图函数的包装器，串联中间件处理流程

                    处理流程：
                    1. 执行预处理阶段
                    2. 调用原始视图函数
                    3. 异常处理阶段
                    4. 响应后处理阶段
                    """
                    result = _pre_process_request(request, *args, **kwargs)
                    if result is not None:
                        return result

                    try:
                        response = await view_func(request, *args, **kwargs)
                    except Exception as e:
                        result = _process_exception(request, e)
                        if result is not None:
                            return result

                    return _post_process_request(request, response)

            else:

                def _view_wrapper(request, *args, **kwargs):
                    """
                    同步视图函数的包装器，串联中间件处理流程

                    处理流程：
                    1. 执行预处理阶段
                    2. 调用原始视图函数
                    3. 异常处理阶段
                    4. 响应后处理阶段
                    """
                    result = _pre_process_request(request, *args, **kwargs)
                    if result is not None:
                        return result

                    try:
                        response = view_func(request, *args, **kwargs)
                    except Exception as e:
                        result = _process_exception(request, e)
                        if result is not None:
                            return result

                    return _post_process_request(request, response)

            return wraps(view_func)(_view_wrapper)

        return _decorator

    return _make_decorator



def sync_and_async_middleware(func):
    """
    Mark a middleware factory as returning a hybrid middleware supporting both
    types of request.
    """
    func.sync_capable = True
    func.async_capable = True
    return func


def sync_only_middleware(func):
    """
    Mark a middleware factory as returning a sync middleware.
    This is the default.
    """
    func.sync_capable = True
    func.async_capable = False
    return func


def async_only_middleware(func):
    """Mark a middleware factory as returning an async middleware."""
    func.sync_capable = False
    func.async_capable = True
    return func
