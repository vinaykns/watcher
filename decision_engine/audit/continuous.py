# -*- encoding: utf-8 -*-
# Copyright (c) 2016 Servionica LTD
# Copyright (c) 2016 Intel Corp
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


import datetime
from dateutil import tz

from apscheduler.jobstores import memory
from croniter import croniter

from watcher.common import context
from watcher.common import scheduling
from watcher.common import utils
from watcher import conf
from watcher.db.sqlalchemy import api as sq_api
from watcher.db.sqlalchemy import job_store
from watcher.decision_engine.audit import base
from watcher import objects


CONF = conf.CONF


class ContinuousAuditHandler(base.AuditHandler):
    def __init__(self):
        super(ContinuousAuditHandler, self).__init__()
        self._scheduler = None
        self.context_show_deleted = context.RequestContext(is_admin=True,
                                                           show_deleted=True)

    @property
    def scheduler(self):
        if self._scheduler is None:
            self._scheduler = scheduling.BackgroundSchedulerService(
                jobstores={
                    'default': job_store.WatcherJobStore(
                        engine=sq_api.get_engine()),
                    'memory': memory.MemoryJobStore()
                }
            )
        return self._scheduler

    def _is_audit_inactive(self, audit):
        audit = objects.Audit.get_by_uuid(
            self.context_show_deleted, audit.uuid)
        if objects.audit.AuditStateTransitionManager().is_inactive(audit):
            # if audit isn't in active states, audit's job must be removed to
            # prevent using of inactive audit in future.
            if self.scheduler.get_jobs():
                [job for job in self.scheduler.get_jobs()
                 if job.name == 'execute_audit' and
                 job.args[0].uuid == audit.uuid][0].remove()
                return True

        return False

    def do_execute(self, audit, request_context):
        # execute the strategy
        solution = self.strategy_context.execute_strategy(
            audit, request_context)

        if audit.audit_type == objects.audit.AuditType.CONTINUOUS.value:
            a_plan_filters = {'audit_uuid': audit.uuid,
                              'state': objects.action_plan.State.RECOMMENDED}
            action_plans = objects.ActionPlan.list(
                request_context, filters=a_plan_filters, eager=True)
            for plan in action_plans:
                plan.state = objects.action_plan.State.CANCELLED
                plan.save()
        return solution

    def _next_cron_time(self, audit):
        if utils.is_cron_like(audit.interval):
            return croniter(audit.interval, datetime.datetime.utcnow()
                            ).get_next(datetime.datetime)

    @classmethod
    def execute_audit(cls, audit, request_context):
        self = cls()
        if not self._is_audit_inactive(audit):
            try:
                self.execute(audit, request_context)
            except Exception:
                raise
            finally:
                if utils.is_int_like(audit.interval):
                    audit.next_run_time = (
                        datetime.datetime.utcnow() +
                        datetime.timedelta(seconds=int(audit.interval)))
                else:
                    audit.next_run_time = self._next_cron_time(audit)
                audit.save()

    def _add_job(self, trigger, audit, audit_context, **trigger_args):
        time_var = 'next_run_time' if trigger_args.get(
            'next_run_time') else 'run_date'
        # We should convert UTC time to local time without tzinfo
        trigger_args[time_var] = trigger_args[time_var].replace(
            tzinfo=tz.tzutc()).astimezone(tz.tzlocal()).replace(tzinfo=None)
        self.scheduler.add_job(self.execute_audit, trigger,
                               args=[audit, audit_context],
                               name='execute_audit',
                               **trigger_args)

    def launch_audits_periodically(self):
        audit_context = context.RequestContext(is_admin=True)
        audit_filters = {
            'audit_type': objects.audit.AuditType.CONTINUOUS.value,
            'state__in': (objects.audit.State.PENDING,
                          objects.audit.State.ONGOING,
                          objects.audit.State.SUCCEEDED)
        }
        audits = objects.Audit.list(
            audit_context, filters=audit_filters, eager=True)
        scheduler_job_args = [
            job.args for job in self.scheduler.get_jobs()
            if job.name == 'execute_audit']
        for audit in audits:
            # if audit is not presented in scheduled audits yet.
            if audit.uuid not in [arg[0].uuid for arg in scheduler_job_args]:
                # if interval is provided with seconds
                if utils.is_int_like(audit.interval):
                    # if audit has already been provided and we need
                    # to restore it after shutdown
                    if audit.next_run_time is not None:
                        old_run_time = audit.next_run_time
                        current = datetime.datetime.utcnow()
                        if old_run_time < current:
                            delta = datetime.timedelta(
                                seconds=(int(audit.interval) - (
                                    current - old_run_time).seconds %
                                    int(audit.interval)))
                            audit.next_run_time = current + delta
                        next_run_time = audit.next_run_time
                    # if audit is new one
                    else:
                        next_run_time = datetime.datetime.utcnow()
                    self._add_job('interval', audit, audit_context,
                                  seconds=int(audit.interval),
                                  next_run_time=next_run_time)

                else:
                    audit.next_run_time = self._next_cron_time(audit)
                    self._add_job('date', audit, audit_context,
                                  run_date=audit.next_run_time)
                audit.save()

    def start(self):
        self.scheduler.add_job(
            self.launch_audits_periodically,
            'interval',
            seconds=CONF.watcher_decision_engine.continuous_audit_interval,
            next_run_time=datetime.datetime.now(),
            jobstore='memory')
        self.scheduler.start()
