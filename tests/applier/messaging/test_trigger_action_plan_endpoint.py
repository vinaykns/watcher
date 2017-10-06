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


import mock

from watcher.applier.messaging import trigger
from watcher.common import utils
from watcher.tests import base


class TestTriggerActionPlan(base.TestCase):
    def __init__(self, *args, **kwds):
        super(TestTriggerActionPlan, self).__init__(*args, **kwds)
        self.applier = mock.MagicMock()
        self.endpoint = trigger.TriggerActionPlan(self.applier)

    def setUp(self):
        super(TestTriggerActionPlan, self).setUp()

    def test_launch_action_plan(self):
        action_plan_uuid = utils.generate_uuid()
        expected_uuid = self.endpoint.launch_action_plan(self.context,
                                                         action_plan_uuid)
        self.assertEqual(expected_uuid, action_plan_uuid)
