from six import string_types
from sqlalchemy.sql import and_, or_

from ichnaea.models.base import JSONMixin

_sentinel = object()


class HashKey(JSONMixin):

    _fields = ()

    def __init__(self, **kw):
        for field in self._fields:
            if field in kw:
                setattr(self, field, kw[field])
            else:
                setattr(self, field, None)

    def __eq__(self, other):
        if isinstance(other, HashKey):
            return self.__dict__ == other.__dict__
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        # emulate a tuple hash
        value = ()
        for field in self._fields:
            value += (getattr(self, field, None), )
        return hash(value)

    def __repr__(self):
        return '{cls}: {data}'.format(cls=self._dottedname, data=self.__dict__)


class HashKeyMixin(object):

    _hashkey_cls = None
    _query_batch = 100

    @classmethod
    def _to_hashkey(cls, obj=_sentinel, **kw):
        if obj is _sentinel:
            obj = kw
        if isinstance(obj, cls._hashkey_cls):
            return obj
        if isinstance(obj, dict):
            return cls._hashkey_cls(**obj)
        if isinstance(obj, (bytes, int) + string_types):
            raise TypeError('Expected dict, hashkey or model object.')
        values = {}
        for field in cls._hashkey_cls._fields:
            values[field] = getattr(obj, field, None)
        return cls._hashkey_cls(**values)

    @classmethod
    def to_hashkey(cls, *args, **kw):
        return cls._to_hashkey(*args, **kw)

    def hashkey(self):
        return self._to_hashkey(self)


class HashKeyQueryMixin(HashKeyMixin):

    @classmethod
    def joinkey(cls, key):
        if not isinstance(key, HashKey):
            if isinstance(key, HashKeyMixin):  # pragma: no cover
                key = key.hashkey()
            else:
                key = cls.to_hashkey(key)
        criterion = ()
        for field in cls._hashkey_cls._fields:
            value = getattr(key, field, _sentinel)
            if value is not _sentinel:
                criterion += (getattr(cls, field) == value, )
        if not criterion:  # pragma: no cover
            # prevent construction of queries without a key restriction
            raise ValueError('Model.joinkey called with empty key.')
        return criterion

    @classmethod
    def getkey(cls, session, key):
        if key is None:  # pragma: no cover
            return None
        return cls.querykey(session, key).first()

    @classmethod
    def querykey(cls, session, key):
        if key is None:  # pragma: no cover
            return None
        return session.query(cls).filter(*cls.joinkey(key))

    @classmethod
    def querykeys(cls, session, keys):
        if not keys:  # pragma: no cover
            # prevent construction of queries without a key restriction
            raise ValueError('Model.querykeys called with empty keys.')

        if len(cls._hashkey_cls._fields) == 1:
            # optimize queries for hashkeys with single fields to use
            # a 'WHERE model.somefield IN (:key_1, :key_2)' query
            field = cls._hashkey_cls._fields[0]
            key_list = []
            for key in keys:
                if isinstance(key, (HashKey, HashKeyMixin)):
                    # extract plain value from class
                    key_list.append(getattr(key, field))
                else:
                    key_list.append(key)
            return session.query(cls).filter(getattr(cls, field).in_(key_list))

        key_filters = []
        for key in keys:
            # create a list of 'and' criteria for each hash key component
            key_filters.append(and_(*cls.joinkey(key)))
        return session.query(cls).filter(or_(*key_filters))

    @classmethod
    def iterkeys(cls, session, keys, extra=None):
        # return all the keys, but batch the actual query depending on
        # an appropriate batch size for each model
        for i in range(0, len(keys), cls._query_batch):
            query = cls.querykeys(session, keys[i:i + cls._query_batch])
            if extra is not None:
                query = extra(query)
            for instance in query.all():
                yield instance
