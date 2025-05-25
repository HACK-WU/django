from collections import defaultdict

from django.apps import apps
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class ContentTypeManager(models.Manager):
    use_in_migrations = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache shared by all the get_for_* methods to speed up
        # ContentType retrieval.
        self._cache = {}

    def get_by_natural_key(self, app_label, model):
        try:
            ct = self._cache[self.db][(app_label, model)]
        except KeyError:
            ct = self.get(app_label=app_label, model=model)
            self._add_to_cache(self.db, ct)
        return ct

    def _get_opts(self, model, for_concrete_model):
        if for_concrete_model:
            model = model._meta.concrete_model
        return model._meta

    def _get_from_cache(self, opts):
        key = (opts.app_label, opts.model_name)
        return self._cache[self.db][key]

    def get_for_model(self, model, for_concrete_model=True):
        """
        获取指定模型对应的ContentType对象，若不存在则创建新对象。通过缓存机制避免重复数据库查询。

        参数:
            model: Django模型类或实例，用于获取模型元数据
            for_concrete_model: 布尔值，是否针对具体模型进行查询（排除代理模型）

        返回值:
            ContentType实例对象，表示模型对应的类型信息

        该方法实现双检查询问数据库策略：
        1. 首先检查本地缓存是否存在有效记录
        2. 缓存未命中时优先尝试直接查询
        3. 最终通过get_or_create处理竞态条件
        """
        opts = self._get_opts(model, for_concrete_model)
        try:
            return self._get_from_cache(opts)
        except KeyError:
            pass

        # 处理缓存未命中情况，执行数据库查询或创建操作
        try:
            # 优先使用直接查询以利用数据库路由策略
            ct = self.get(app_label=opts.app_label, model=opts.model_name)
        except self.model.DoesNotExist:
            # 处理记录不存在场景，使用get_or_create保证原子性操作
            ct, created = self.get_or_create(
                app_label=opts.app_label,
                model=opts.model_name,
            )
        # 将新获取/创建的ContentType对象写入缓存
        self._add_to_cache(self.db, ct)
        return ct

    def get_for_models(self, *models, for_concrete_models=True):
        """
        Given *models, return a dictionary mapping {model: content_type}.
        """
        results = {}
        # Models that aren't already in the cache grouped by app labels.
        needed_models = defaultdict(set)
        # Mapping of opts to the list of models requiring it.
        needed_opts = defaultdict(list)
        for model in models:
            opts = self._get_opts(model, for_concrete_models)
            try:
                ct = self._get_from_cache(opts)
            except KeyError:
                needed_models[opts.app_label].add(opts.model_name)
                needed_opts[(opts.app_label, opts.model_name)].append(model)
            else:
                results[model] = ct
        if needed_opts:
            # Lookup required content types from the DB.
            condition = Q(
                *(
                    Q(("app_label", app_label), ("model__in", models))
                    for app_label, models in needed_models.items()
                ),
                _connector=Q.OR,
            )
            cts = self.filter(condition)
            for ct in cts:
                opts_models = needed_opts.pop((ct.app_label, ct.model), [])
                for model in opts_models:
                    results[model] = ct
                self._add_to_cache(self.db, ct)
        # Create content types that weren't in the cache or DB.
        for (app_label, model_name), opts_models in needed_opts.items():
            ct = self.create(app_label=app_label, model=model_name)
            self._add_to_cache(self.db, ct)
            for model in opts_models:
                results[model] = ct
        return results

    def get_for_id(self, id):
        """
        Lookup a ContentType by ID. Use the same shared cache as get_for_model
        (though ContentTypes are not created on-the-fly by get_by_id).
        """
        try:
            ct = self._cache[self.db][id]
        except KeyError:
            # This could raise a DoesNotExist; that's correct behavior and will
            # make sure that only correct ctypes get stored in the cache dict.
            ct = self.get(pk=id)
            self._add_to_cache(self.db, ct)
        return ct

    def clear_cache(self):
        """
        Clear out the content-type cache.
        """
        self._cache.clear()

    def _add_to_cache(self, using, ct):
        """Insert a ContentType into the cache."""
        # Note it's possible for ContentType objects to be stale; model_class()
        # will return None. Hence, there is no reliance on
        # model._meta.app_label here, just using the model fields instead.
        key = (ct.app_label, ct.model)
        self._cache.setdefault(using, {})[key] = ct
        self._cache.setdefault(using, {})[ct.id] = ct


class ContentType(models.Model):
    app_label = models.CharField(max_length=100)
    model = models.CharField(_("python model class name"), max_length=100)
    objects = ContentTypeManager()

    class Meta:
        verbose_name = _("content type")
        verbose_name_plural = _("content types")
        db_table = "django_content_type"
        unique_together = [["app_label", "model"]]

    def __str__(self):
        return self.app_labeled_name

    @property
    def name(self):
        model = self.model_class()
        if not model:
            return self.model
        return str(model._meta.verbose_name)

    @property
    def app_labeled_name(self):
        model = self.model_class()
        if not model:
            return self.model
        return "%s | %s" % (
            model._meta.app_config.verbose_name,
            model._meta.verbose_name,
        )

    def model_class(self):
        """Return the model class for this type of content."""
        try:
            return apps.get_model(self.app_label, self.model)
        except LookupError:
            return None

    def get_object_for_this_type(self, using=None, **kwargs):
        """
        Return an object of this type for the keyword arguments given.
        Basically, this is a proxy around this object_type's get_object() model
        method. The ObjectNotExist exception, if thrown, will not be caught,
        so code that calls this method should catch it.
        """
        return self.model_class()._base_manager.using(using).get(**kwargs)

    def get_all_objects_for_this_type(self, **kwargs):
        """
        Return all objects of this type for the keyword arguments given.
        """
        return self.model_class()._base_manager.filter(**kwargs)

    def natural_key(self):
        return (self.app_label, self.model)
