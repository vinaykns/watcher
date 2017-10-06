# -*- encoding: utf-8 -*-
# Copyright (c) 2015 b<>com
#
# Authors: Jean-Emile DARTOIS <jean-emile.dartois@b-com.com>
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
#

"""
This component is in charge of executing the
:ref:`Action Plan <action_plan_definition>` built by the
:ref:`Watcher Decision Engine <watcher_decision_engine_definition>`.

See: :doc:`../architecture` for more details on this component.
"""

import abc
import six


@six.add_metaclass(abc.ABCMeta)
class BaseApplier(object):
    @abc.abstractmethod
    def execute(self, action_plan_uuid):
        raise NotImplementedError()
