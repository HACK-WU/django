"""
Cross Site Request Forgery Middleware.

This module provides a middleware that implements protection
against request forgeries from other sites.
"""

import logging
import string
from collections import defaultdict
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import DisallowedHost, ImproperlyConfigured
from django.http import HttpHeaders, UnreadablePostError
from django.urls import get_callable
from django.utils.cache import patch_vary_headers
from django.utils.crypto import constant_time_compare, get_random_string
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import cached_property
from django.utils.http import is_same_domain
from django.utils.log import log_response
from django.utils.regex_helper import _lazy_re_compile

"""
CSRF（跨站请求伪造）防护相关配置与错误信息定义模块。

该模块定义了CSRF令牌验证过程中的关键配置参数、正则表达式规则以及
多种验证失败场景的错误信息模板，用于Django框架的安全中间件处理。
"""

# 获取CSRF安全日志记录器实例，用于记录与CSRF防护相关的安全事件
logger = logging.getLogger("django.security.csrf")

# 预编译正则表达式，用于检测CSRF令牌中包含非法字符的情况
# 匹配任何不在CSRF_ALLOWED_CHARS范围内的字符
invalid_token_chars_re = _lazy_re_compile("[^a-zA-Z0-9]")

# 错误原因字符串模板：请求来源验证失败（未匹配信任源）
REASON_BAD_ORIGIN = "Origin checking failed - %s does not match any trusted origins."
# 错误原因字符串模板：缺少Referer头信息
REASON_NO_REFERER = "Referer checking failed - no Referer."
# 错误原因字符串模板：Referer来源验证失败
REASON_BAD_REFERER = "Referer checking failed - %s does not match any trusted origins."
# 错误原因字符串模板：CSRF cookie未设置
REASON_NO_CSRF_COOKIE = "CSRF cookie not set."
# 错误原因字符串模板：请求中缺失CSRF令牌
REASON_CSRF_TOKEN_MISSING = "CSRF token missing."
# 错误原因字符串模板：Referer头格式异常
REASON_MALFORMED_REFERER = "Referer checking failed - Referer is malformed."
# 错误原因字符串模板：HTTP与HTTPS协议混用导致的安全验证失败
REASON_INSECURE_REFERER = (
    "Referer checking failed - Referer is insecure while host is secure."
)

# 令牌格式错误专用提示信息
# 令牌长度不符合要求的提示模板
REASON_INCORRECT_LENGTH = "has incorrect length"
# 令牌包含非法字符的提示模板
REASON_INVALID_CHARACTERS = "has invalid characters"

# CSRF安全密钥字节长度（32字节对应256位加密强度）
CSRF_SECRET_LENGTH = 32
# CSRF令牌总长度（为密钥长度的两倍，用于存储防篡改签名）
CSRF_TOKEN_LENGTH = 2 * CSRF_SECRET_LENGTH
# 允许在CSRF令牌中使用的字符集（大小写字母+数字）
CSRF_ALLOWED_CHARS = string.ascii_letters + string.digits
# 会话中存储CSRF令牌的键名定义
CSRF_SESSION_KEY = "_csrftoken"


def _get_failure_view():
    """Return the view to be used for CSRF rejections."""
    return get_callable(settings.CSRF_FAILURE_VIEW)


def _get_new_csrf_string():
    return get_random_string(CSRF_SECRET_LENGTH, allowed_chars=CSRF_ALLOWED_CHARS)


def _mask_cipher_secret(secret):
    """
    Given a secret (assumed to be a string of CSRF_ALLOWED_CHARS), generate a
    token by adding a mask and applying it to the secret.
    """
    mask = _get_new_csrf_string()
    chars = CSRF_ALLOWED_CHARS
    pairs = zip((chars.index(x) for x in secret), (chars.index(x) for x in mask))
    cipher = "".join(chars[(x + y) % len(chars)] for x, y in pairs)
    return mask + cipher


def _unmask_cipher_token(token):
    """
    Given a token (assumed to be a string of CSRF_ALLOWED_CHARS, of length
    CSRF_TOKEN_LENGTH, and that its first half is a mask), use it to decrypt
    the second half to produce the original secret.
    """
    mask = token[:CSRF_SECRET_LENGTH]
    token = token[CSRF_SECRET_LENGTH:]
    chars = CSRF_ALLOWED_CHARS
    pairs = zip((chars.index(x) for x in token), (chars.index(x) for x in mask))
    return "".join(chars[x - y] for x, y in pairs)  # Note negative values are ok


def _add_new_csrf_cookie(request):
    """Generate a new random CSRF_COOKIE value, and add it to request.META."""
    csrf_secret = _get_new_csrf_string()
    request.META.update(
        {
            "CSRF_COOKIE": csrf_secret,
            "CSRF_COOKIE_NEEDS_UPDATE": True,
        }
    )
    return csrf_secret


def get_token(request):
    """
    Return the CSRF token required for a POST form. The token is an
    alphanumeric value. A new token is created if one is not already set.

    A side effect of calling this function is to make the csrf_protect
    decorator and the CsrfViewMiddleware add a CSRF cookie and a 'Vary: Cookie'
    header to the outgoing response.  For this reason, you may need to use this
    function lazily, as is done by the csrf context processor.
    """
    if "CSRF_COOKIE" in request.META:
        csrf_secret = request.META["CSRF_COOKIE"]
        # Since the cookie is being used, flag to send the cookie in
        # process_response() (even if the client already has it) in order to
        # renew the expiry timer.
        request.META["CSRF_COOKIE_NEEDS_UPDATE"] = True
    else:
        csrf_secret = _add_new_csrf_cookie(request)
    return _mask_cipher_secret(csrf_secret)


def rotate_token(request):
    """
    Change the CSRF token in use for a request - should be done on login
    for security purposes.
    """
    _add_new_csrf_cookie(request)


class InvalidTokenFormat(Exception):
    def __init__(self, reason):
        self.reason = reason


def _check_token_format(token):
    """
    Raise an InvalidTokenFormat error if the token has an invalid length or
    characters that aren't allowed. The token argument can be a CSRF cookie
    secret or non-cookie CSRF token, and either masked or unmasked.
    """
    if len(token) not in (CSRF_TOKEN_LENGTH, CSRF_SECRET_LENGTH):
        raise InvalidTokenFormat(REASON_INCORRECT_LENGTH)
    # Make sure all characters are in CSRF_ALLOWED_CHARS.
    if invalid_token_chars_re.search(token):
        raise InvalidTokenFormat(REASON_INVALID_CHARACTERS)


def _does_token_match(request_csrf_token, csrf_secret):
    """
    检查给定的CSRF令牌是否与给定的CSRF密钥匹配，必要时先对令牌进行解掩。

    此函数假设request_csrf_token参数已经被验证具有正确的长度
    （CSRF_SECRET_LENGTH或CSRF_TOKEN_LENGTH字符）和允许的字符，并且如果它的长度
    为CSRF_TOKEN_LENGTH，它是一个被掩的密钥。

    参数:
    request_csrf_token (str): 来自请求的CSRF令牌，可能被掩。
    csrf_secret (str): 用于比较的CSRF密钥。

    返回:
    bool: 如果解掩后的CSRF令牌与CSRF密钥匹配，则返回True，否则返回False。
    """
    # 只解掩长度正好为CSRF_TOKEN_LENGTH字符的令牌。
    if len(request_csrf_token) == CSRF_TOKEN_LENGTH:
        request_csrf_token = _unmask_cipher_token(request_csrf_token)
    # 确保解掩后的令牌长度为CSRF_SECRET_LENGTH。
    assert len(request_csrf_token) == CSRF_SECRET_LENGTH
    # 使用constant_time_compare函数进行安全的字符串比较。
    return constant_time_compare(request_csrf_token, csrf_secret)



class RejectRequest(Exception):
    def __init__(self, reason):
        self.reason = reason


class CsrfViewMiddleware(MiddlewareMixin):
    """
    Require a present and correct csrfmiddlewaretoken for POST requests that
    have a CSRF cookie, and set an outgoing CSRF cookie.

    This middleware should be used in conjunction with the {% csrf_token %}
    template tag.
    """

    @cached_property
    def csrf_trusted_origins_hosts(self):
        return [
            urlsplit(origin).netloc.lstrip("*")
            for origin in settings.CSRF_TRUSTED_ORIGINS
        ]

    @cached_property
    def allowed_origins_exact(self):
        return {origin for origin in settings.CSRF_TRUSTED_ORIGINS if "*" not in origin}

    @cached_property
    def allowed_origin_subdomains(self):
        """
        A mapping of allowed schemes to list of allowed netlocs, where all
        subdomains of the netloc are allowed.
        """
        allowed_origin_subdomains = defaultdict(list)
        for parsed in (
            urlsplit(origin)
            for origin in settings.CSRF_TRUSTED_ORIGINS
            if "*" in origin
        ):
            allowed_origin_subdomains[parsed.scheme].append(parsed.netloc.lstrip("*"))
        return allowed_origin_subdomains

    # The _accept and _reject methods currently only exist for the sake of the
    # requires_csrf_token decorator.
    def _accept(self, request):
        # Avoid checking the request twice by adding a custom attribute to
        # request.  This will be relevant when both decorator and middleware
        # are used.
        request.csrf_processing_done = True
        return None

    def _reject(self, request, reason):
        response = _get_failure_view()(request, reason=reason)
        log_response(
            "Forbidden (%s): %s",
            reason,
            request.path,
            response=response,
            request=request,
            logger=logger,
        )
        return response

    def _get_secret(self, request):
        """
        获取与请求关联的原始CSRF密钥，若请求未携带密钥则返回None。

        参数:
            request (HttpRequest): 需要获取CSRF密钥的HTTP请求对象

        返回值:
            str/None: 返回原始CSRF密钥字符串或None

        异常:
            当CSRF_USE_SESSIONS启用时：
                - ImproperlyConfigured: 若request.session未设置且CSRF_USE_SESSIONS启用
            当CSRF_USE_SESSIONS禁用时：
                - InvalidTokenFormat: 若cookie中的CSRF密钥包含非法字符或长度无效
        """
        # 处理使用会话存储CSRF密钥的情况
        if settings.CSRF_USE_SESSIONS:
            try:
                csrf_secret = request.session.get(CSRF_SESSION_KEY)
            except AttributeError:
                # 会话中间件配置异常处理
                raise ImproperlyConfigured(
                    "CSRF_USE_SESSIONS is enabled, but request.session is not "
                    "set. SessionMiddleware must appear before CsrfViewMiddleware "
                    "in MIDDLEWARE."
                )
        else:
            # 处理使用cookie存储CSRF密钥的情况
            try:
                csrf_secret = request.COOKIES[settings.CSRF_COOKIE_NAME]
            except KeyError:
                csrf_secret = None
            else:
                # 验证CSRF密钥格式合法性（长度和字符集）
                _check_token_format(csrf_secret)

        # 处理空密钥情况
        if csrf_secret is None:
            return None

        # 兼容旧版本Django的密钥解密处理
        # Django 4.0之前版本会对密钥进行掩码处理
        if len(csrf_secret) == CSRF_TOKEN_LENGTH:
            csrf_secret = _unmask_cipher_token(csrf_secret)
        return csrf_secret

    def _set_csrf_cookie(self, request, response):
        if settings.CSRF_USE_SESSIONS:
            if request.session.get(CSRF_SESSION_KEY) != request.META["CSRF_COOKIE"]:
                request.session[CSRF_SESSION_KEY] = request.META["CSRF_COOKIE"]
        else:
            response.set_cookie(
                settings.CSRF_COOKIE_NAME,
                request.META["CSRF_COOKIE"],
                max_age=settings.CSRF_COOKIE_AGE,
                domain=settings.CSRF_COOKIE_DOMAIN,
                path=settings.CSRF_COOKIE_PATH,
                secure=settings.CSRF_COOKIE_SECURE,
                httponly=settings.CSRF_COOKIE_HTTPONLY,
                samesite=settings.CSRF_COOKIE_SAMESITE,
            )
            # Set the Vary header since content varies with the CSRF cookie.
            patch_vary_headers(response, ("Cookie",))

    def _origin_verified(self, request):
        """
        验证请求的来源是否合法。

        参数:
            request (HttpRequest): 接收的HTTP请求对象，包含元数据和主机信息。

        返回值:
            bool: True表示来源已验证通过，False表示未通过。
        """
        request_origin = request.META["HTTP_ORIGIN"]
        try:
            good_host = request.get_host()
        except DisallowedHost:
            pass
        else:
            # 构建预期的源地址并进行精确匹配验证
            good_origin = "%s://%s" % (
                "https" if request.is_secure() else "http",
                good_host,
            )
            if request_origin == good_origin:
                return True

        # 检查是否在完全允许的来源列表中
        if request_origin in self.allowed_origins_exact:
            return True

        # 解析请求来源的URL结构
        try:
            parsed_origin = urlsplit(request_origin)
        except ValueError:
            return False
        request_scheme = parsed_origin.scheme
        request_netloc = parsed_origin.netloc

        # 检查是否存在匹配的允许子域名
        return any(
            is_same_domain(request_netloc, host)
            for host in self.allowed_origin_subdomains.get(request_scheme, ())
        )


    def _check_referer(self, request):
        """
        验证请求的 Referer 头是否符合安全要求。

        参数:
            request (HttpRequest): 需要验证的 HTTP 请求对象

        返回值:
            无显式返回值。若验证通过则静默返回，否则抛出 RejectRequest 异常。

        异常:
            RejectRequest: 当 Referer 验证失败时抛出，包含以下原因：
                - REASON_NO_REFERER: 缺少 Referer 头
                - REASON_MALFORMED_REFERER: Referer 格式错误
                - REASON_INSECURE_REFERER: Referer 协议非 HTTPS
                - REASON_BAD_REFERER: Referer 域名不匹配
        """
        # 检查 Referer 头是否存在
        referer = request.META.get("HTTP_REFERER")
        if referer is None:
            raise RejectRequest(REASON_NO_REFERER)

        # 解析 Referer URL 结构
        try:
            referer = urlsplit(referer)
        except ValueError:
            raise RejectRequest(REASON_MALFORMED_REFERER)

        # 验证 URL 基本结构有效性
        if "" in (referer.scheme, referer.netloc):
            raise RejectRequest(REASON_MALFORMED_REFERER)

        # 强制 HTTPS 协议要求
        if referer.scheme != "https":
            raise RejectRequest(REASON_INSECURE_REFERER)

        # 检查是否匹配信任的源域名列表
        if any(
            is_same_domain(referer.netloc, host)
            for host in self.csrf_trusted_origins_hosts
        ):
            return

        # 确定允许的 Referer 基准域名
        good_referer = (
            settings.SESSION_COOKIE_DOMAIN
            if settings.CSRF_USE_SESSIONS
            else settings.CSRF_COOKIE_DOMAIN
        )
        if good_referer is None:
            # 无显式配置时验证当前主机合法性
            try:
                good_referer = request.get_host()
            except DisallowedHost:
                raise RejectRequest(REASON_BAD_REFERER % referer.geturl())
        else:
            server_port = request.get_port()
            if server_port not in ("443", "80"):
                good_referer = "%s:%s" % (good_referer, server_port)

        # 最终域名匹配验证
        if not is_same_domain(referer.netloc, good_referer):
            raise RejectRequest(REASON_BAD_REFERER % referer.geturl())

    def _bad_token_message(self, reason, token_source):
        if token_source != "POST":
            # Assume it is a settings.CSRF_HEADER_NAME value.
            header_name = HttpHeaders.parse_header_name(token_source)
            token_source = f"the {header_name!r} HTTP header"
        return f"CSRF token from {token_source} {reason}."

    def _check_token(self, request):
        """
        验证请求中的CSRF令牌与存储的密钥是否匹配

        参数:
            request: HttpRequest对象，包含请求元数据和内容

        返回值:
            无返回值，验证失败时抛出RejectRequest异常

        异常:
            RejectRequest: 当检测到CSRF令牌缺失、格式错误或不匹配时抛出
            InvalidTokenFormat: 当令牌格式不符合要求时捕获并转换异常
        """
        # 获取CSRF密钥阶段
        # 通过self._get_secret()获取当前请求的CSRF密钥
        # 注意：rotate_token()可能在认证中间件中被调用
        try:
            csrf_secret = self._get_secret(request)
        except InvalidTokenFormat as exc:
            raise RejectRequest(f"CSRF cookie {exc.reason}.")

        if csrf_secret is None:
            # 安全策略：强制POST请求必须携带CSRF cookie
            # 该策略可有效防御所有CSRF攻击（包括登录CSRF）
            raise RejectRequest(REASON_NO_CSRF_COOKIE)

        # 令牌获取阶段
        # 优先从POST数据中获取CSRF令牌
        request_csrf_token = ""
        if request.method == "POST":
            try:
                request_csrf_token = request.POST.get("csrfmiddlewaretoken", "")
            except UnreadablePostError:
                # 特殊处理：当POST数据读取失败时静默处理
                # 避免process_view抛出异常导致服务中断
                pass

        # 回退机制：支持AJAX请求的X-CSRFToken头部
        # 支持PUT/DELETE方法的令牌验证
        if request_csrf_token == "":
            try:
                # 令牌可能来自DOM或cookie（带掩码/不带掩码）
                request_csrf_token = request.META[settings.CSRF_HEADER_NAME]
            except KeyError:
                raise RejectRequest(REASON_CSRF_TOKEN_MISSING)
            token_source = settings.CSRF_HEADER_NAME
        else:
            token_source = "POST"

        # 令牌验证阶段
        # 格式校验：验证令牌长度和编码格式
        try:
            _check_token_format(request_csrf_token)
        except InvalidTokenFormat as exc:
            reason = self._bad_token_message(exc.reason, token_source)
            raise RejectRequest(reason)

        # 安全比对：防御时序攻击的令牌匹配检查
        if not _does_token_match(request_csrf_token, csrf_secret):
            reason = self._bad_token_message("incorrect", token_source)
            raise RejectRequest(reason)

    def process_request(self, request):
        """
        处理客户端请求，主要负责处理CSRF（跨站请求伪造）保护的逻辑。

        该方法首先尝试获取请求中的CSRF密钥，如果密钥格式无效，则为用户添加新的CSRF Cookie。
        如果密钥有效，则更新请求的元数据，以便后续的请求验证可以使用该密钥。

        参数:
        - request: HttpRequest对象，包含当前请求的所有信息。

        返回值:
        无返回值，但可能会修改request对象的META字典，添加CSRF_COOKIE键。
        """
        try:
            # 尝试获取请求中的CSRF密钥
            csrf_secret = self._get_secret(request)
        except InvalidTokenFormat:
            # 如果密钥格式无效，为用户添加新的CSRF Cookie
            _add_new_csrf_cookie(request)
        else:
            # 如果密钥有效且不为空，则更新请求的元数据
            if csrf_secret is not None:
                # 使用相同的密钥下次。如果密钥最初被屏蔽，这也会导致它被未屏蔽的形式替换，
                # 但这只会在密钥无论如何都会被保存的情况下发生。
                request.META["CSRF_COOKIE"] = csrf_secret

    def process_view(self, request, callback, callback_args, callback_kwargs):
        """
        处理视图请求的CSRF验证中间件逻辑

        参数:
            request: HttpRequest对象，包含请求元数据和状态信息
            callback: 视图函数对象，可能带有csrf_exempt装饰器标记
            callback_args: 视图函数的位置参数元组
            callback_kwargs: 视图函数的关键字参数字典

        返回值:
            None表示继续中间件链处理
            中间件响应对象（由_accept/_reject方法生成）表示终止请求处理

        该方法实现完整的CSRF攻击防护流程，包含：
        1. 安全方法放行（GET/HEAD/OPTIONS/TRACE）
        2. 双重提交Cookie验证机制
        3. HTTPS请求的严格来源验证（Origin/Referer检查）
        4. CSRF Token有效性验证
        """

        # 跳过已处理过的请求
        # 防止重复执行CSRF验证逻辑
        if getattr(request, "csrf_processing_done", False):
            return None

        # 豁免标记视图
        # 支持csrf_exempt装饰器绕过CSRF检查
        if getattr(callback, "csrf_exempt", False):
            return None

        # 放行安全方法
        # 根据RFC 9110定义，只对非安全方法进行保护
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return self._accept(request)

        # 测试模式绕过
        # 用于测试用例禁用CSRF检查但仍保持Cookie流程
        if getattr(request, "_dont_enforce_csrf_checks", False):
            return self._accept(request)

        # Origin头验证
        # 检测跨域请求伪造攻击，优先使用Origin头验证
        if "HTTP_ORIGIN" in request.META:
            if not self._origin_verified(request):
                return self._reject(
                    request, REASON_BAD_ORIGIN % request.META["HTTP_ORIGIN"]
                )
        # HTTPS请求的Referer头验证
        # 当缺少Origin头时，对HTTPS请求实施严格Referer检查
        # 防范中间人攻击利用同域HTTP连接劫持HTTPS请求
        elif request.is_secure():
            try:
                self._check_referer(request)
            except RejectRequest as exc:
                return self._reject(request, exc.reason)

        # CSRF Token验证
        # 核心防御机制：验证CSRF令牌与Cookie的匹配性
        try:
            self._check_token(request)
        except RejectRequest as exc:
            return self._reject(request, exc.reason)

        # 最终放行
        # 所有安全检查通过后的正常流程
        return self._accept(request)

    def process_response(self, request, response):
        if request.META.get("CSRF_COOKIE_NEEDS_UPDATE"):
            self._set_csrf_cookie(request, response)
            # Unset the flag to prevent _set_csrf_cookie() from being
            # unnecessarily called again in process_response() by other
            # instances of CsrfViewMiddleware. This can happen e.g. when both a
            # decorator and middleware are used. However,
            # CSRF_COOKIE_NEEDS_UPDATE is still respected in subsequent calls
            # e.g. in case rotate_token() is called in process_response() later
            # by custom middleware but before those subsequent calls.
            request.META["CSRF_COOKIE_NEEDS_UPDATE"] = False

        return response
