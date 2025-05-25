from asgiref.sync import sync_to_async

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Exists, OuterRef, Q

UserModel = get_user_model()


class BaseBackend:
    def authenticate(self, request, **kwargs):
        return None

    async def aauthenticate(self, request, **kwargs):
        return await sync_to_async(self.authenticate)(request, **kwargs)

    def get_user(self, user_id):
        return None

    async def aget_user(self, user_id):
        return await sync_to_async(self.get_user)(user_id)

    def get_user_permissions(self, user_obj, obj=None):
        return set()

    async def aget_user_permissions(self, user_obj, obj=None):
        return await sync_to_async(self.get_user_permissions)(user_obj, obj)

    def get_group_permissions(self, user_obj, obj=None):
        return set()

    async def aget_group_permissions(self, user_obj, obj=None):
        return await sync_to_async(self.get_group_permissions)(user_obj, obj)

    def get_all_permissions(self, user_obj, obj=None):
        return {
            *self.get_user_permissions(user_obj, obj=obj),
            *self.get_group_permissions(user_obj, obj=obj),
        }

    async def aget_all_permissions(self, user_obj, obj=None):
        return {
            *await self.aget_user_permissions(user_obj, obj=obj),
            *await self.aget_group_permissions(user_obj, obj=obj),
        }

    def has_perm(self, user_obj, perm, obj=None):
        return perm in self.get_all_permissions(user_obj, obj=obj)

    async def ahas_perm(self, user_obj, perm, obj=None):
        return perm in await self.aget_all_permissions(user_obj, obj)


class ModelBackend(BaseBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a nonexistent user (#20760).
            UserModel().set_password(password)
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user

    async def aauthenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return
        try:
            user = await UserModel._default_manager.aget_by_natural_key(username)
        except UserModel.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a nonexistent user (#20760).
            UserModel().set_password(password)
        else:
            if await user.acheck_password(password) and self.user_can_authenticate(
                user
            ):
                return user

    def user_can_authenticate(self, user):
        """
        Reject users with is_active=False. Custom user models that don't have
        that attribute are allowed.
        """
        return getattr(user, "is_active", True)

    def _get_user_permissions(self, user_obj):
        return user_obj.user_permissions.all()

    def _get_group_permissions(self, user_obj):
        return Permission.objects.filter(group__in=user_obj.groups.all())

    def _get_permissions(self, user_obj, obj, from_name):
        """
        获取用户的权限集合

        此方法根据用户对象、权限所属对象和权限来源（群组或用户）来返回用户的权限集合
        如果用户不是活跃状态、是匿名用户或者权限所属对象不为空，则返回空集合
        否则，根据来源从缓存中获取权限集合，如果缓存不存在，则进行查询并缓存结果

        参数:
            user_obj: 用户对象，用于获取权限的用户
            obj: 权限所属对象，目前未使用，保留参数以适应未来可能的需求
            from_name: 权限来源，可以是"group"（群组）或"user"（用户）

        返回值:
            权限集合，包含用户从指定来源获取的所有权限
        """
        # 验证用户状态，非活跃、匿名用户或存在权限所属对象时直接返回空集合
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        # 构建缓存名称，用于存储用户或群组权限
        perm_cache_name = "_%s_perm_cache" % from_name

        # 检查用户对象是否已有权限缓存，如果没有则进行查询
        if not hasattr(user_obj, perm_cache_name):
            # 超级用户直接查询所有权限
            if user_obj.is_superuser:
                perms = Permission.objects.all()
            else:
                # 根据from_name调用相应的权限获取方法
                perms = getattr(self, "_get_%s_permissions" % from_name)(user_obj)

            # 将查询结果转换为权限字符串集合，并设置为用户对象的属性
            # 比如：
            # [('app01', 'add_car'), ('app01', 'change_car')]
            perms = perms.values_list("content_type__app_label", "codename").order_by()
            setattr(
                user_obj, perm_cache_name, {"%s.%s" % (ct, name) for ct, name in perms}
            )

        # perm_cache_name 格式为：
        # {"app01.add_book","app01.delete_book" }

        # 返回权限集合
        return getattr(user_obj, perm_cache_name)

    async def _aget_permissions(self, user_obj, obj, from_name):
        """See _get_permissions()."""
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        perm_cache_name = "_%s_perm_cache" % from_name
        if not hasattr(user_obj, perm_cache_name):
            if user_obj.is_superuser:
                perms = Permission.objects.all()
            else:
                perms = getattr(self, "_get_%s_permissions" % from_name)(user_obj)
            perms = perms.values_list("content_type__app_label", "codename").order_by()
            setattr(
                user_obj,
                perm_cache_name,
                {"%s.%s" % (ct, name) async for ct, name in perms},
            )
        return getattr(user_obj, perm_cache_name)

    def get_user_permissions(self, user_obj, obj=None):
        """
        Return a set of permission strings the user `user_obj` has from their
        `user_permissions`.
        """
        return self._get_permissions(user_obj, obj, "user")

    async def aget_user_permissions(self, user_obj, obj=None):
        """See get_user_permissions()."""
        return await self._aget_permissions(user_obj, obj, "user")

    def get_group_permissions(self, user_obj, obj=None):
        """
        Return a set of permission strings the user `user_obj` has from the
        groups they belong.
        """
        return self._get_permissions(user_obj, obj, "group")

    async def aget_group_permissions(self, user_obj, obj=None):
        """See get_group_permissions()."""
        return await self._aget_permissions(user_obj, obj, "group")

    def get_all_permissions(self, user_obj, obj=None):
        """
        获取指定用户的全部权限

        此方法针对给定的用户对象，返回其拥有的所有权限的集合如果用户不符合活跃条件，
        或是匿名用户，或是为特定对象请求权限，则返回空集合如果用户权限未被缓存，则调用
        父类方法获取权限并缓存结果，以优化后续查询

        参数:
            user_obj: User对象，需获取权限的用户
            obj: 可选参数，若提供则表示为特定对象请求权限，目前不支持此功能，应为None

        返回值:
            set类型，包含用户的所有权限字符串如果用户不活跃、是匿名用户或obj参数非None，则返回空集合
        """
        # 检查用户是否为活跃状态、非匿名用户，且不涉及特定对象的权限查询
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        # 检查用户对象是否已缓存权限信息，若未缓存则进行获取并缓存
        if not hasattr(user_obj, "_perm_cache"):
            user_obj._perm_cache = super().get_all_permissions(user_obj)

        # 返回缓存的权限信息
        return user_obj._perm_cache


    def has_perm(self, user_obj, perm, obj=None):
        return user_obj.is_active and super().has_perm(user_obj, perm, obj=obj)

    async def ahas_perm(self, user_obj, perm, obj=None):
        return user_obj.is_active and await super().ahas_perm(user_obj, perm, obj=obj)

    def has_module_perms(self, user_obj, app_label):
        """
        Return True if user_obj has any permissions in the given app_label.
        """
        return user_obj.is_active and any(
            perm[: perm.index(".")] == app_label
            for perm in self.get_all_permissions(user_obj)
        )

    async def ahas_module_perms(self, user_obj, app_label):
        """See has_module_perms()"""
        return user_obj.is_active and any(
            perm[: perm.index(".")] == app_label
            for perm in await self.aget_all_permissions(user_obj)
        )

    def with_perm(self, perm, is_active=True, include_superusers=True, obj=None):
        """
        Return users that have permission "perm". By default, filter out
        inactive users and include superusers.
        """
        if isinstance(perm, str):
            try:
                app_label, codename = perm.split(".")
            except ValueError:
                raise ValueError(
                    "Permission name should be in the form "
                    "app_label.permission_codename."
                )
        elif not isinstance(perm, Permission):
            raise TypeError(
                "The `perm` argument must be a string or a permission instance."
            )

        if obj is not None:
            return UserModel._default_manager.none()

        permission_q = Q(group__user=OuterRef("pk")) | Q(user=OuterRef("pk"))
        if isinstance(perm, Permission):
            permission_q &= Q(pk=perm.pk)
        else:
            permission_q &= Q(codename=codename, content_type__app_label=app_label)

        user_q = Exists(Permission.objects.filter(permission_q))
        if include_superusers:
            user_q |= Q(is_superuser=True)
        if is_active is not None:
            user_q &= Q(is_active=is_active)

        return UserModel._default_manager.filter(user_q)

    def get_user(self, user_id):
        try:
            user = UserModel._default_manager.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None

    async def aget_user(self, user_id):
        try:
            user = await UserModel._default_manager.aget(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None


class AllowAllUsersModelBackend(ModelBackend):
    def user_can_authenticate(self, user):
        return True


class RemoteUserBackend(ModelBackend):
    """
    This backend is to be used in conjunction with the ``RemoteUserMiddleware``
    found in the middleware module of this package, and is used when the server
    is handling authentication outside of Django.

    By default, the ``authenticate`` method creates ``User`` objects for
    usernames that don't already exist in the database.  Subclasses can disable
    this behavior by setting the ``create_unknown_user`` attribute to
    ``False``.
    """

    # Create a User object if not already in the database?
    create_unknown_user = True

    def authenticate(self, request, remote_user):
        """
        The username passed as ``remote_user`` is considered trusted. Return
        the ``User`` object with the given username. Create a new ``User``
        object if ``create_unknown_user`` is ``True``.

        Return None if ``create_unknown_user`` is ``False`` and a ``User``
        object with the given username is not found in the database.
        """
        if not remote_user:
            return
        created = False
        user = None
        username = self.clean_username(remote_user)

        # Note that this could be accomplished in one try-except clause, but
        # instead we use get_or_create when creating unknown users since it has
        # built-in safeguards for multiple threads.
        if self.create_unknown_user:
            user, created = UserModel._default_manager.get_or_create(
                **{UserModel.USERNAME_FIELD: username}
            )
        else:
            try:
                user = UserModel._default_manager.get_by_natural_key(username)
            except UserModel.DoesNotExist:
                pass
        user = self.configure_user(request, user, created=created)
        return user if self.user_can_authenticate(user) else None

    async def aauthenticate(self, request, remote_user):
        """See authenticate()."""
        if not remote_user:
            return
        created = False
        user = None
        username = self.clean_username(remote_user)

        # Note that this could be accomplished in one try-except clause, but
        # instead we use get_or_create when creating unknown users since it has
        # built-in safeguards for multiple threads.
        if self.create_unknown_user:
            user, created = await UserModel._default_manager.aget_or_create(
                **{UserModel.USERNAME_FIELD: username}
            )
        else:
            try:
                user = await UserModel._default_manager.aget_by_natural_key(username)
            except UserModel.DoesNotExist:
                pass
        user = await self.aconfigure_user(request, user, created=created)
        return user if self.user_can_authenticate(user) else None

    def clean_username(self, username):
        """
        Perform any cleaning on the "username" prior to using it to get or
        create the user object.  Return the cleaned username.

        By default, return the username unchanged.
        """
        return username

    def configure_user(self, request, user, created=True):
        """
        Configure a user and return the updated user.

        By default, return the user unmodified.
        """
        return user

    async def aconfigure_user(self, request, user, created=True):
        """See configure_user()"""
        return await sync_to_async(self.configure_user)(request, user, created)


class AllowAllUsersRemoteUserBackend(RemoteUserBackend):
    def user_can_authenticate(self, user):
        return True
