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
from oslo_log import log

from watcher.applier.action_plan import base
from watcher.applier import default
from watcher.common import exception
from watcher import notifications
from watcher import objects
from watcher.objects import fields

LOG = log.getLogger(__name__)


class DefaultActionPlanHandler(base.BaseActionPlanHandler):

    def __init__(self, context, service, action_plan_uuid):
        super(DefaultActionPlanHandler, self).__init__()
        self.ctx = context
        self.service = service
        self.action_plan_uuid = action_plan_uuid

    def execute(self):
        try:
            action_plan = objects.ActionPlan.get_by_uuid(
                self.ctx, self.action_plan_uuid, eager=True)
            if action_plan.state == objects.action_plan.State.CANCELLED:
                self._update_action_from_pending_to_cancelled()
                return
            action_plan.state = objects.action_plan.State.ONGOING
            action_plan.save()
            notifications.action_plan.send_action_notification(
                self.ctx, action_plan,
                action=fields.NotificationAction.EXECUTION,
                phase=fields.NotificationPhase.START)

            applier = default.DefaultApplier(self.ctx, self.service)
            applier.execute(self.action_plan_uuid)

            action_plan.state = objects.action_plan.State.SUCCEEDED
            notifications.action_plan.send_action_notification(
                self.ctx, action_plan,
                action=fields.NotificationAction.EXECUTION,
                phase=fields.NotificationPhase.END)

        except exception.ActionPlanCancelled as e:
            LOG.exception(e)
            action_plan.state = objects.action_plan.State.CANCELLED
            self._update_action_from_pending_to_cancelled()

        except Exception as e:
            LOG.exception(e)
            action_plan.state = objects.action_plan.State.FAILED
            notifications.action_plan.send_action_notification(
                self.ctx, action_plan,
                action=fields.NotificationAction.EXECUTION,
                priority=fields.NotificationPriority.ERROR,
                phase=fields.NotificationPhase.ERROR)
        finally:
            action_plan.save()

    def _update_action_from_pending_to_cancelled(self):
        filters = {'action_plan_uuid': self.action_plan_uuid,
                   'state': objects.action.State.PENDING}
        actions = objects.Action.list(self.ctx, filters=filters, eager=True)
        if actions:
            for a in actions:
                a.state = objects.action.State.CANCELLED
                a.save()
