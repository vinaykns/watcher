# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import jsonpatch
from oslo_config import cfg
from oslo_utils import reflection
from oslo_utils import uuidutils
import pecan
import wsme

from watcher._i18n import _
from watcher.common import utils
from watcher import objects

CONF = cfg.CONF


JSONPATCH_EXCEPTIONS = (jsonpatch.JsonPatchException,
                        jsonpatch.JsonPointerException,
                        KeyError)


def validate_limit(limit):
    if limit is None:
        return CONF.api.max_limit

    if limit <= 0:
        # Case where we don't a valid limit value
        raise wsme.exc.ClientSideError(_("Limit must be positive"))

    if limit and not CONF.api.max_limit:
        # Case where we don't have an upper limit
        return limit

    return min(CONF.api.max_limit, limit)


def validate_sort_dir(sort_dir):
    if sort_dir not in ['asc', 'desc']:
        raise wsme.exc.ClientSideError(_("Invalid sort direction: %s. "
                                         "Acceptable values are "
                                         "'asc' or 'desc'") % sort_dir)


def validate_search_filters(filters, allowed_fields):
    # Very lightweight validation for now
    # todo: improve this (e.g. https://www.parse.com/docs/rest/guide/#queries)
    for filter_name in filters.keys():
        if filter_name not in allowed_fields:
            raise wsme.exc.ClientSideError(
                _("Invalid filter: %s") % filter_name)


def apply_jsonpatch(doc, patch):
    for p in patch:
        if p['op'] == 'add' and p['path'].count('/') == 1:
            if p['path'].lstrip('/') not in doc:
                msg = _('Adding a new attribute (%s) to the root of '
                        ' the resource is not allowed')
                raise wsme.exc.ClientSideError(msg % p['path'])
    return jsonpatch.apply_patch(doc, jsonpatch.JsonPatch(patch))


def get_patch_value(patch, key):
    for p in patch:
        if p['op'] == 'replace' and p['path'] == '/%s' % key:
            return p['value']


def check_audit_state_transition(patch, initial):
    is_transition_valid = True
    state_value = get_patch_value(patch, "state")
    if state_value is not None:
        is_transition_valid = objects.audit.AuditStateTransitionManager(
            ).check_transition(initial, state_value)
    return is_transition_valid


def as_filters_dict(**filters):
    filters_dict = {}
    for filter_name, filter_value in filters.items():
        if filter_value:
            filters_dict[filter_name] = filter_value

    return filters_dict


def get_resource(resource, resource_id, eager=False):
    """Get the resource from the uuid, id or logical name.

    :param resource: the resource type.
    :param resource_id: the UUID, ID or logical name of the resource.

    :returns: The resource.
    """
    resource = getattr(objects, resource)

    _get = None
    if utils.is_int_like(resource_id):
        resource_id = int(resource_id)
        _get = resource.get
    elif uuidutils.is_uuid_like(resource_id):
        _get = resource.get_by_uuid
    else:
        _get = resource.get_by_name

    method_signature = reflection.get_signature(_get)
    if 'eager' in method_signature.parameters:
        return _get(pecan.request.context, resource_id, eager=eager)

    return _get(pecan.request.context, resource_id)
