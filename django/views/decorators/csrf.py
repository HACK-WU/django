from functools import wraps

from asgiref.sync import iscoroutinefunction

from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.utils.decorators import decorator_from_middleware

csrf_protect = decorator_from_middleware(CsrfViewMiddleware)
csrf_protect.__name__ = "csrf_protect"
csrf_protect.__doc__ = """
This decorator adds CSRF protection in exactly the same way as
CsrfViewMiddleware, but it can be used on a per view basis.  Using both, or
using the decorator multiple times, is harmless and efficient.
"""


class _EnsureCsrfToken(CsrfViewMiddleware):
    # Behave like CsrfViewMiddleware but don't reject requests or log warnings.
    def _reject(self, request, reason):
        return None


requires_csrf_token = decorator_from_middleware(_EnsureCsrfToken)
requires_csrf_token.__name__ = "requires_csrf_token"
requires_csrf_token.__doc__ = """
Use this decorator on views that need a correct csrf_token available to
RequestContext, but without the CSRF protection that csrf_protect
enforces.
"""


class _EnsureCsrfCookie(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return None

    def process_view(self, request, callback, callback_args, callback_kwargs):
        retval = super().process_view(request, callback, callback_args, callback_kwargs)
        # Force process_response to send the cookie
        get_token(request)
        return retval


ensure_csrf_cookie = decorator_from_middleware(_EnsureCsrfCookie)
ensure_csrf_cookie.__name__ = "ensure_csrf_cookie"
ensure_csrf_cookie.__doc__ = """
Use this decorator to ensure that a view sets a CSRF cookie, whether or not it
uses the csrf_token template tag, or the CsrfViewMiddleware is used.
"""


def csrf_exempt(view_func):
    """Mark a view function as being exempt from the CSRF view protection.

    Args:
        view_func (callable): 需要免除CSRF保护的视图函数或协程函数。可以是同步或异步视图函数

    Returns:
        callable: 返回带有csrf_exempt标记的包装函数。包装函数会保留原视图函数的元数据，
                  同时设置csrf_exempt=True属性来禁用CSRF中间件保护

    Decorator实现说明：
        1. 通过判断视图函数类型创建对应的包装函数（同步/异步）
        2. 采用包装函数而非直接设置属性的方式，避免装饰器产生副作用
        3. 使用wraps装饰器保留原函数元数据
    """

    # 根据视图函数类型创建包装函数
    if iscoroutinefunction(view_func):
        # 异步视图处理：创建异步包装函数
        async def _view_wrapper(request, *args, **kwargs):
            return await view_func(request, *args, **kwargs)
    else:
        # 同步视图处理：创建同步包装函数
        def _view_wrapper(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)

    # 设置CSRF豁免标记（核心功能实现）
    _view_wrapper.csrf_exempt = True

    # 保留原函数元数据后返回包装函数
    return wraps(view_func)(_view_wrapper)

