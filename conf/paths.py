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

import os

PATH_OPTS = [
    cfg.StrOpt('pybasedir',
               default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                    '../')),
               help='Directory where the watcher python module is installed.'),
    cfg.StrOpt('bindir',
               default='$pybasedir/bin',
               help='Directory where watcher binaries are installed.'),
    cfg.StrOpt('state_path',
               default='$pybasedir',
               help="Top-level directory for maintaining watcher's state."),
]


def basedir_def(*args):
    """Return an uninterpolated path relative to $pybasedir."""
    return os.path.join('$pybasedir', *args)


def bindir_def(*args):
    """Return an uninterpolated path relative to $bindir."""
    return os.path.join('$bindir', *args)


def state_path_def(*args):
    """Return an uninterpolated path relative to $state_path."""
    return os.path.join('$state_path', *args)


def register_opts(conf):
    conf.register_opts(PATH_OPTS)


def list_opts():
    return [('DEFAULT', PATH_OPTS)]
