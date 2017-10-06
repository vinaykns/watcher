# -*- encoding: utf-8 -*-
# Copyright (c) 2017 Servionica
#
# Authors: Alexander Chadin <a.chadin@servionica.ru>
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

gnocchi_client = cfg.OptGroup(name='gnocchi_client',
                              title='Configuration Options for Gnocchi')

GNOCCHI_CLIENT_OPTS = [
    cfg.StrOpt('api_version',
               default='1',
               help='Version of Gnocchi API to use in gnocchiclient.'),
    cfg.StrOpt('endpoint_type',
               default='internalURL',
               help='Type of endpoint to use in gnocchi client.'
                    'Supported values: internalURL, publicURL, adminURL'
                    'The default is internalURL.'),
    cfg.IntOpt('query_max_retries',
               default=10,
               help='How many times Watcher is trying to query again'),
    cfg.IntOpt('query_timeout',
               default=1,
               help='How many seconds Watcher should wait to do query again')]


def register_opts(conf):
    conf.register_group(gnocchi_client)
    conf.register_opts(GNOCCHI_CLIENT_OPTS, group=gnocchi_client)


def list_opts():
    return [('gnocchi_client', GNOCCHI_CLIENT_OPTS)]
