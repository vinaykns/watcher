# -*- encoding: utf-8 -*-
# Copyright (c) 2016 Intel Corp
#
# Authors: Prudhvi Rao Shedimbi <prudhvi.rao.shedimbi@intel.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg

neutron_client = cfg.OptGroup(name='neutron_client',
                              title='Configuration Options for Neutron')

NEUTRON_CLIENT_OPTS = [
    cfg.StrOpt('api_version',
               default='2.0',
               help='Version of Neutron API to use in neutronclient.'),
    cfg.StrOpt('endpoint_type',
               default='publicURL',
               help='Type of endpoint to use in neutronclient.'
                    'Supported values: internalURL, publicURL, adminURL'
                    'The default is publicURL.')]


def register_opts(conf):
    conf.register_group(neutron_client)
    conf.register_opts(NEUTRON_CLIENT_OPTS, group=neutron_client)


def list_opts():
    return [('neutron_client', NEUTRON_CLIENT_OPTS)]
