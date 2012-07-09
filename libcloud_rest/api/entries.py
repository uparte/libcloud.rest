# -*- coding:utf-8 -*-
from functools import partial

try:
    import simplejson as json
except ImportError:
    import json

from libcloud.compute import base as compute_base

from libcloud_rest.api import validators as valid
from libcloud_rest.exception import MalformedJSONError, ValidationError,\
    NoSuchObjectError, MissingArguments


class Field(object):
    """
    Base class for all field types.
    """
    validator_cls = None
    typename = None

    def __init__(self, description=None, name=None, required=True):
        self.description = description
        self.name = name
        self._required = required
        self.validator = self.validator_cls(required=required, name=name)

    def _set_required(self, required):
        self._required = required

    def _get_required(self):
        return self._required

    required = property(_get_required, _set_required)

    def validate(self, json_data):
        try:
            data = json_data[self.name]
        except (KeyError, TypeError):
            if self.required:
                raise MissingArguments([self.name])
            return
        self.validator(data)

    def contribute_to_class(self, cls, name):
        self.model = cls
        self.name = name
        self.validator.name = name

    def get_description_dict(self):
        return {'name': self.name,
                'description': self.description,
                'type': self.typename}


class StringField(Field):
    validator_cls = valid.StringValidator
    typename = 'string'


class DictField(Field):
    validator_cls = partial(valid.DictValidator, {})
    typename = 'dictionary'


class LibcloudObjectEntryBase(type):
    """
    Metaclass for all entries.
    """

    def __new__(mcs, name, bases, attrs):
        super_new = super(LibcloudObjectEntryBase, mcs).__new__
        parents = [b for b in bases if isinstance(b, LibcloudObjectEntryBase)]
        if not parents:
            # If this isn't a subclass of Model, don't do anything special.
            return super_new(mcs, name, bases, attrs)
            # Create the class.
        module = attrs.pop('__module__', None)
        new_class = super_new(mcs, name, bases, {'__module__': module})
        new_class.add_to_class('_fields', [])

        # Add all attributes to the class.
        for obj_name, obj in attrs.items():
            new_class.add_to_class(obj_name, obj)

        return new_class

    def add_to_class(cls, name, value):
        if isinstance(value, Field):
            value.contribute_to_class(cls, name)
            cls._fields.append(value)
        else:
            setattr(cls, name, value)


class BasicEntry(object):
    """
    Just describe interface.
    """
    def _get_json(self, data):
        """

        @param data:
        @type data:
        @return:
        @rtype:
        @raise: MalformedJsonError
        """
        try:
            json_data = json.loads(data)
        except (ValueError, TypeError), e:
            raise MalformedJSONError(detail=str(e))
        if not isinstance(json_data, dict):
            raise MalformedJSONError('Bad json format')
        return json_data

    def _validate(self, json_data):
        """

        @param json_data:
        @type json_data:
        @raise: MissingArguments
                ValidationError
        """
        pass

    def _get_json_and_validate(self, data):
        json_data = self._get_json(data)
        self._validate(json_data)
        return json_data

    def get_arguments(self):
        """

        """
        pass

    def to_json(self, obj):
        """

        @param obj:
        @type obj:
        @raise: ValueError
        """
        pass

    def from_json(self, obj, driver):
        """

        @param obj:
        @type obj:
        @param driver:
        @type driver:
        @raise: MissingArguments
                ValidationError
                _get_object errors
        """
        pass

    def _contains_arguments(self, json_data):
        pass


class LibcloudObjectEntry(BasicEntry):
    __metaclass__ = LibcloudObjectEntryBase
    render_attrs = None

    def __init__(self, name, typename, description, **kwargs):
        self.name = name
        self.typename = typename
        self.description = description
        if 'default' in kwargs:
            self.default = kwargs['default']

    @classmethod
    def to_json(cls, obj):
        try:
            data = dict(((name, getattr(obj, name))
                         for name in cls.render_attrs))
        except AttributeError, e:
            #FIXME: create new error class for this
            raise ValueError('Can not represent object as json %s' % (str(e)))
        return json.dumps(data)

    def _get_object(self, json_data, driver):
        raise NotImplementedError()

    def _contains_arguments(self, json_data):
        for field in self._fields:
            if field.name in json_data:
                return True
        return False

    def from_json(self, data, driver):
        json_data = self._get_json(data)
        if not self._contains_arguments(json_data) \
                and hasattr(self, 'default'):
            return self.default
        self._validate(json_data)
        return self._get_object(json_data, driver)

    def _validate(self, json_data):
        missed_args = []
        try:
            for field in self._fields:
                field.validate(json_data)
        except MissingArguments, error:
            missed_args.extend(error.arguments)
        if missed_args:
            raise MissingArguments(arguments=missed_args)

    @classmethod
    def get_arguments(cls):
        return [field.get_description_dict() for field in cls._fields]


class SimpleEntry(BasicEntry):
    def __init__(self, name, typename, description, **kwargs):
        self.name = name
        if 'default' in kwargs:
            self.default = kwargs['default']
        self.field = simple_types_fields[typename](description, name)

    def _validate(self, json_data):
        self.field.validate(json_data)

    def get_arguments(self):
        argument_dict = self.field.get_description_dict()
        if hasattr(self, 'default'):
            argument_dict['default'] = self.default
        return [argument_dict]

    def to_json(self, obj):
        try:
            data = json.dumps({self.name: obj})
            json_data = self._get_json(data)
            self._validate(json_data)
            return data
        except (MalformedJSONError, ValidationError), e:
            raise ValueError('Can not represent object as json %s' % (str(e)))

    def _contains_arguments(self, json_data):
        if self.field.name in json_data:
            return True
        return False

    def from_json(self, data, driver=None):
        json_data = self._get_json(data)
        if not self._contains_arguments(json_data)\
                and hasattr(self, 'default'):
            return self.default
        self._validate(json_data)
        return json_data[self.name]


class NodeEntry(LibcloudObjectEntry):
    render_attrs = ['id', 'name', 'state', 'public_ips']
    node_id = StringField('ID of the node which should be used')

    def _get_object(self, json_data, driver):
        nodes_list = driver.list_nodes()
        node_id = json_data['node_id']
        for node in nodes_list:
            if node_id == node.id:
                return node
        raise NoSuchObjectError(obj_type='Node')


class NodeAuthSSHKeyEntry(LibcloudObjectEntry):
    render_attrs = []
    node_pubkey = StringField('An SSH key to be installed for'
                              ' authentication to a node.')

    def _get_object(self, json_data, driver):
        return compute_base.NodeAuthSSHKey(json_data['node_pubkey'])


class NodeAuthPasswordEntry(LibcloudObjectEntry):
    render_attrs = []
    node_password = StringField('A password to be used for'
                                ' authentication to a node.')

    def _get_object(self, json_data, driver):
        return compute_base.NodeAuthPassword(json_data['node_password'])

simple_types_fields = {
    'C{str}': StringField,
    'C{dict}': DictField,
}

complex_entries = {
    'L{Node}': NodeEntry,
    'L{NodeAuthSSHKey}': NodeAuthSSHKeyEntry,
    'L{NodeAuthPassword}': NodeAuthPasswordEntry,
}


class OneOfEntry(BasicEntry):
    def __init__(self, name, typenames, description, **kwargs):
        self.name = name
        if 'default' in kwargs:
            self.default = kwargs['default']
        self.typenames = typenames
        self.description = description
        self.entries = [Entry(name, (typename, ), description)
                        for typename in typenames]

    def _validate(self, json_data):
        missed_arguments = []
        for entry in self.entries:
            try:
                entry._validate(json_data)
                break
            except (MissingArguments, ), e:
                missed_arguments.extend(e.arguments)
        else:
            raise MissingArguments(arguments=missed_arguments)

    def get_arguments(self):
        arguments = []
        for entry in self.entries:
            args = entry.get_arguments()
            arguments.extend(args)
        return arguments

    def to_json(self, obj):
        for entry in self.entries:
            try:
                json_data = entry.to_json(obj)
                return json_data
            except (ValueError, ), e:
                continue
        else:
            raise ValueError('Can not represent object as json %s' % (str(e)))

    def from_json(self, data, driver):
        missed_arguments = []
        validation_errors = []
        contain_arguments = []
        results = []
        json_data = self._get_json(data)
        for entry in self.entries:
            try:
                contain_arguments.append(entry._contains_arguments(json_data))
                results.append(entry.from_json(data, driver))
            except MissingArguments, e:
                missed_arguments.extend(e.arguments)
            except ValidationError, e:
                validation_errors.append(e)
        if len(results) == 1:
            return results[0]
        elif validation_errors:
            error_message = ' || '.join([e.message for e in validation_errors])
            raise ValidationError(error_message)
        elif not results and not any(contain_arguments) \
                and hasattr(self, 'default'):
            return self.default
        elif missed_arguments:
            missed_arguments = ' or '.join(str(a) for a in missed_arguments)
            raise MissingArguments(arguments=missed_arguments)
        raise ValueError('Too many arguments provided')


class Entry(object):
    def __new__(cls, name, typenames, description='', **kwargs):
        if len(typenames) == 1:
            typename = typenames[0]
            if typename in simple_types_fields:
                entry_class = SimpleEntry
            elif typename in complex_entries:
                entry_class = complex_entries[typename]
            else:
                raise ValueError('Unknown typename %s' % (typename))
            return entry_class(name, typename, description, **kwargs)
        return OneOfEntry(name, typenames, description, **kwargs)
