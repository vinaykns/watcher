# -*- encoding: utf-8 -*-
# Copyright (c) 2016 b<>com
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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
from taskflow import engines
from taskflow import exceptions as tf_exception
from taskflow.patterns import graph_flow as gf
from taskflow import task as flow_task

from watcher.applier.workflow_engine import base
from watcher.common import exception
from watcher import objects

LOG = log.getLogger(__name__)


class DefaultWorkFlowEngine(base.BaseWorkFlowEngine):
    """Taskflow as a workflow engine for Watcher

    Full documentation on taskflow at
    http://docs.openstack.org/developer/taskflow/
    """

    def decider(self, history):
        # FIXME(jed) not possible with the current Watcher Planner
        #
        # decider – A callback function that will be expected to
        # decide at runtime whether v should be allowed to execute
        # (or whether the execution of v should be ignored,
        # and therefore not executed). It is expected to take as single
        # keyword argument history which will be the execution results of
        # all u decideable links that have v as a target. It is expected
        # to return a single boolean
        # (True to allow v execution or False to not).
        return True

    @classmethod
    def get_config_opts(cls):
        return [
            cfg.IntOpt(
                'max_workers',
                default=processutils.get_worker_count(),
                min=1,
                required=True,
                help='Number of workers for taskflow engine '
                     'to execute actions.')
            ]

    def execute(self, actions):
        try:
            # NOTE(jed) We want to have a strong separation of concern
            # between the Watcher planner and the Watcher Applier in order
            # to us the possibility to support several workflow engine.
            # We want to provide the 'taskflow' engine by
            # default although we still want to leave the possibility for
            # the users to change it.
            # The current implementation uses graph with linked actions.
            # todo(jed) add olso conf for retry and name
            flow = gf.Flow("watcher_flow")
            actions_uuid = {}
            for a in actions:
                task = TaskFlowActionContainer(a, self)
                flow.add(task)
                actions_uuid[a.uuid] = task

            for a in actions:
                for parent_id in a.parents:
                    flow.link(actions_uuid[parent_id], actions_uuid[a.uuid],
                              decider=self.decider)

            e = engines.load(
                flow, engine='parallel',
                max_workers=self.config.max_workers)
            e.run()

            return flow

        except exception.ActionPlanCancelled as e:
            raise

        except tf_exception.WrappedFailure as e:
            if e.check("watcher.common.exception.ActionPlanCancelled"):
                raise exception.ActionPlanCancelled
            else:
                raise exception.WorkflowExecutionException(error=e)

        except Exception as e:
            raise exception.WorkflowExecutionException(error=e)


class TaskFlowActionContainer(base.BaseTaskFlowActionContainer):
    def __init__(self, db_action, engine):
        name = "action_type:{0} uuid:{1}".format(db_action.action_type,
                                                 db_action.uuid)
        super(TaskFlowActionContainer, self).__init__(name, db_action, engine)

    def do_pre_execute(self):
        self.engine.notify(self._db_action, objects.action.State.ONGOING)
        LOG.debug("Pre-condition action: %s", self.name)
        self.action.pre_condition()

    def do_execute(self, *args, **kwargs):
        LOG.debug("Running action: %s", self.name)

        # NOTE: For result is False, set action state fail
        result = self.action.execute()
        if result is False:
            self.engine.notify(self._db_action,
                               objects.action.State.FAILED)
        else:
            self.engine.notify(self._db_action,
                               objects.action.State.SUCCEEDED)

    def do_post_execute(self):
        LOG.debug("Post-condition action: %s", self.name)
        self.action.post_condition()

    def do_revert(self, *args, **kwargs):
        LOG.warning("Revert action: %s", self.name)
        try:
            # TODO(jed): do we need to update the states in case of failure?
            self.action.revert()
        except Exception as e:
            LOG.exception(e)
            LOG.critical("Oops! We need a disaster recover plan.")

    def do_abort(self, *args, **kwargs):
        LOG.warning("Aborting action: %s", self.name)
        try:
            result = self.action.abort()
            if result:
                # Aborted the action.
                self.engine.notify(self._db_action,
                                   objects.action.State.CANCELLED)
            else:
                self.engine.notify(self._db_action,
                                   objects.action.State.SUCCEEDED)
        except Exception as e:
            self.engine.notify(self._db_action, objects.action.State.FAILED)
            LOG.exception(e)


class TaskFlowNop(flow_task.Task):
    """This class is used in case of the workflow have only one Action.

    We need at least two atoms to create a link.
    """
    def execute(self):
        pass
