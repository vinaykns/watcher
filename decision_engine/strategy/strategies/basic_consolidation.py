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
*Good server consolidation strategy*

Consolidation of VMs is essential to achieve energy optimization in cloud
environments such as OpenStack. As VMs are spinned up and/or moved over time,
it becomes necessary to migrate VMs among servers to lower the costs. However,
migration of VMs introduces runtime overheads and consumes extra energy, thus
a good server consolidation strategy should carefully plan for migration in
order to both minimize energy consumption and comply to the various SLAs.

This algorithm not only minimizes the overall number of used servers, but also
minimizes the number of migrations.

It has been developed only for tests. You must have at least 2 physical compute
nodes to run it, so you can easily run it on DevStack. It assumes that live
migration is possible on your OpenStack cluster.

"""

import datetime

from oslo_config import cfg
from oslo_log import log

from watcher._i18n import _
from watcher.common import exception
from watcher.datasource import ceilometer as ceil
from watcher.datasource import gnocchi as gnoc
from watcher.datasource import monasca as mon
from watcher.decision_engine.model import element
from watcher.decision_engine.strategy.strategies import base

LOG = log.getLogger(__name__)


class BasicConsolidation(base.ServerConsolidationBaseStrategy):
    """Basic offline consolidation using live migration"""

    HOST_CPU_USAGE_METRIC_NAME = 'compute.node.cpu.percent'
    INSTANCE_CPU_USAGE_METRIC_NAME = 'cpu_util'

    METRIC_NAMES = dict(
        ceilometer=dict(
            host_cpu_usage='compute.node.cpu.percent',
            instance_cpu_usage='cpu_util'),
        monasca=dict(
            host_cpu_usage='cpu.percent',
            instance_cpu_usage='vm.cpu.utilization_perc'),
        gnocchi=dict(
            host_cpu_usage='compute.node.cpu.percent',
            instance_cpu_usage='cpu_util'),
    )

    MIGRATION = "migrate"
    CHANGE_NOVA_SERVICE_STATE = "change_nova_service_state"

    def __init__(self, config, osc=None):
        """Basic offline Consolidation using live migration

        :param config: A mapping containing the configuration of this strategy
        :type config: :py:class:`~.Struct` instance
        :param osc: :py:class:`~.OpenStackClients` instance
        """
        super(BasicConsolidation, self).__init__(config, osc)

        # set default value for the number of enabled compute nodes
        self.number_of_enabled_nodes = 0
        # set default value for the number of released nodes
        self.number_of_released_nodes = 0
        # set default value for the number of migrations
        self.number_of_migrations = 0

        # set default value for the efficacy
        self.efficacy = 100

        self._ceilometer = None
        self._monasca = None
        self._gnocchi = None

        # TODO(jed): improve threshold overbooking?
        self.threshold_mem = 1
        self.threshold_disk = 1
        self.threshold_cores = 1

    @classmethod
    def get_name(cls):
        return "basic"

    @property
    def migration_attempts(self):
        return self.input_parameters.get('migration_attempts', 0)

    @property
    def period(self):
        return self.input_parameters.get('period', 7200)

    @property
    def granularity(self):
        return self.input_parameters.get('granularity', 300)

    @classmethod
    def get_display_name(cls):
        return _("Basic offline consolidation")

    @classmethod
    def get_translatable_display_name(cls):
        return "Basic offline consolidation"

    @classmethod
    def get_schema(cls):
        # Mandatory default setting for each element
        return {
            "properties": {
                "migration_attempts": {
                    "description": "Maximum number of combinations to be "
                                   "tried by the strategy while searching "
                                   "for potential candidates. To remove the "
                                   "limit, set it to 0 (by default)",
                    "type": "number",
                    "default": 0
                },
                "period": {
                    "description": "The time interval in seconds for "
                                   "getting statistic aggregation",
                    "type": "number",
                    "default": 7200
                },
                "granularity": {
                    "description": "The time between two measures in an "
                                   "aggregated timeseries of a metric.",
                    "type": "number",
                    "default": 300
                },
            },
        }

    @classmethod
    def get_config_opts(cls):
        return [
            cfg.StrOpt(
                "datasource",
                help="Data source to use in order to query the needed metrics",
                default="ceilometer",
                choices=["ceilometer", "monasca", "gnocchi"]),
            cfg.BoolOpt(
                "check_optimize_metadata",
                help="Check optimize metadata field in instance before "
                     "migration",
                default=False),
        ]

    @property
    def ceilometer(self):
        if self._ceilometer is None:
            self._ceilometer = ceil.CeilometerHelper(osc=self.osc)
        return self._ceilometer

    @ceilometer.setter
    def ceilometer(self, ceilometer):
        self._ceilometer = ceilometer

    @property
    def monasca(self):
        if self._monasca is None:
            self._monasca = mon.MonascaHelper(osc=self.osc)
        return self._monasca

    @monasca.setter
    def monasca(self, monasca):
        self._monasca = monasca

    @property
    def gnocchi(self):
        if self._gnocchi is None:
            self._gnocchi = gnoc.GnocchiHelper(osc=self.osc)
        return self._gnocchi

    @gnocchi.setter
    def gnocchi(self, gnocchi):
        self._gnocchi = gnocchi

    def check_migration(self, source_node, destination_node,
                        instance_to_migrate):
        """Check if the migration is possible

        :param source_node: the current node of the virtual machine
        :param destination_node: the destination of the virtual machine
        :param instance_to_migrate: the instance / virtual machine
        :return: True if the there is enough place otherwise false
        """
        if source_node == destination_node:
            return False

        LOG.debug('Migrate instance %s from %s to  %s',
                  instance_to_migrate, source_node, destination_node)

        total_cores = 0
        total_disk = 0
        total_mem = 0
        for instance in self.compute_model.get_node_instances(
                destination_node):
            total_cores += instance.vcpus
            total_disk += instance.disk
            total_mem += instance.memory

        # capacity requested by the compute node
        total_cores += instance_to_migrate.vcpus
        total_disk += instance_to_migrate.disk
        total_mem += instance_to_migrate.memory

        return self.check_threshold(destination_node, total_cores, total_disk,
                                    total_mem)

    def check_threshold(self, destination_node, total_cores,
                        total_disk, total_mem):
        """Check threshold

        Check the threshold value defined by the ratio of
        aggregated CPU capacity of VMs on one node to CPU capacity
        of this node must not exceed the threshold value.

        :param destination_node: the destination of the virtual machine
        :param total_cores: total cores of the virtual machine
        :param total_disk: total disk size used by the virtual machine
        :param total_mem: total memory used by the virtual machine
        :return: True if the threshold is not exceed
        """
        cpu_capacity = destination_node.vcpus
        disk_capacity = destination_node.disk
        memory_capacity = destination_node.memory

        return (cpu_capacity >= total_cores * self.threshold_cores and
                disk_capacity >= total_disk * self.threshold_disk and
                memory_capacity >= total_mem * self.threshold_mem)

    def calculate_weight(self, compute_resource, total_cores_used,
                         total_disk_used, total_memory_used):
        """Calculate weight of every resource

        :param compute_resource:
        :param total_cores_used:
        :param total_disk_used:
        :param total_memory_used:
        :return:
        """
        cpu_capacity = compute_resource.vcpus
        disk_capacity = compute_resource.disk
        memory_capacity = compute_resource.memory

        score_cores = (1 - (float(cpu_capacity) - float(total_cores_used)) /
                       float(cpu_capacity))

        # It's possible that disk_capacity is 0, e.g., m1.nano.disk = 0
        if disk_capacity == 0:
            score_disk = 0
        else:
            score_disk = (1 - (float(disk_capacity) - float(total_disk_used)) /
                          float(disk_capacity))

        score_memory = (
            1 - (float(memory_capacity) - float(total_memory_used)) /
            float(memory_capacity))
        # TODO(jed): take in account weight
        return (score_cores + score_disk + score_memory) / 3

    def get_node_cpu_usage(self, node):
        metric_name = self.METRIC_NAMES[
            self.config.datasource]['host_cpu_usage']
        if self.config.datasource == "ceilometer":
            resource_id = "%s_%s" % (node.uuid, node.hostname)
            return self.ceilometer.statistic_aggregation(
                resource_id=resource_id,
                meter_name=metric_name,
                period=self.period,
                aggregate='avg',
            )
        elif self.config.datasource == "gnocchi":
            resource_id = "%s_%s" % (node.uuid, node.hostname)
            stop_time = datetime.datetime.utcnow()
            start_time = stop_time - datetime.timedelta(
                seconds=int(self.period))
            return self.gnocchi.statistic_aggregation(
                resource_id=resource_id,
                metric=metric_name,
                granularity=self.granularity,
                start_time=start_time,
                stop_time=stop_time,
                aggregation='mean'
            )
        elif self.config.datasource == "monasca":
            statistics = self.monasca.statistic_aggregation(
                meter_name=metric_name,
                dimensions=dict(hostname=node.uuid),
                period=self.period,
                aggregate='avg'
            )
            cpu_usage = None
            for stat in statistics:
                avg_col_idx = stat['columns'].index('avg')
                values = [r[avg_col_idx] for r in stat['statistics']]
                value = float(sum(values)) / len(values)
                cpu_usage = value

            return cpu_usage

        raise exception.UnsupportedDataSource(
            strategy=self.name, datasource=self.config.datasource)

    def get_instance_cpu_usage(self, instance):
        metric_name = self.METRIC_NAMES[
            self.config.datasource]['instance_cpu_usage']
        if self.config.datasource == "ceilometer":
            return self.ceilometer.statistic_aggregation(
                resource_id=instance.uuid,
                meter_name=metric_name,
                period=self.period,
                aggregate='avg'
            )
        elif self.config.datasource == "gnocchi":
            stop_time = datetime.datetime.utcnow()
            start_time = stop_time - datetime.timedelta(
                seconds=int(self.period))
            return self.gnocchi.statistic_aggregation(
                resource_id=instance.uuid,
                metric=metric_name,
                granularity=self.granularity,
                start_time=start_time,
                stop_time=stop_time,
                aggregation='mean',
            )
        elif self.config.datasource == "monasca":
            statistics = self.monasca.statistic_aggregation(
                meter_name=metric_name,
                dimensions=dict(resource_id=instance.uuid),
                period=self.period,
                aggregate='avg'
            )
            cpu_usage = None
            for stat in statistics:
                avg_col_idx = stat['columns'].index('avg')
                values = [r[avg_col_idx] for r in stat['statistics']]
                value = float(sum(values)) / len(values)
                cpu_usage = value
            return cpu_usage

        raise exception.UnsupportedDataSource(
            strategy=self.name, datasource=self.config.datasource)

    def calculate_score_node(self, node):
        """Calculate the score that represent the utilization level

        :param node: :py:class:`~.ComputeNode` instance
        :return: Score for the given compute node
        :rtype: float
        """
        host_avg_cpu_util = self.get_node_cpu_usage(node)

        if host_avg_cpu_util is None:
            resource_id = "%s_%s" % (node.uuid, node.hostname)
            LOG.error(
                "No values returned by %(resource_id)s "
                "for %(metric_name)s" % dict(
                    resource_id=resource_id,
                    metric_name=self.METRIC_NAMES[
                        self.config.datasource]['host_cpu_usage']))
            host_avg_cpu_util = 100

        total_cores_used = node.vcpus * (host_avg_cpu_util / 100.0)

        return self.calculate_weight(node, total_cores_used, 0, 0)

    def calculate_score_instance(self, instance):
        """Calculate Score of virtual machine

        :param instance: the virtual machine
        :return: score
        """
        instance_cpu_utilization = self.get_instance_cpu_usage(instance)
        if instance_cpu_utilization is None:
            LOG.error(
                "No values returned by %(resource_id)s "
                "for %(metric_name)s" % dict(
                    resource_id=instance.uuid,
                    metric_name=self.METRIC_NAMES[
                        self.config.datasource]['instance_cpu_usage']))
            instance_cpu_utilization = 100

        total_cores_used = instance.vcpus * (instance_cpu_utilization / 100.0)

        return self.calculate_weight(instance, total_cores_used, 0, 0)

    def add_change_service_state(self, resource_id, state):
        parameters = {'state': state}
        self.solution.add_action(action_type=self.CHANGE_NOVA_SERVICE_STATE,
                                 resource_id=resource_id,
                                 input_parameters=parameters)

    def add_migration(self,
                      resource_id,
                      migration_type,
                      source_node,
                      destination_node):
        parameters = {'migration_type': migration_type,
                      'source_node': source_node,
                      'destination_node': destination_node}
        self.solution.add_action(action_type=self.MIGRATION,
                                 resource_id=resource_id,
                                 input_parameters=parameters)

    def compute_score_of_nodes(self):
        """Calculate score of nodes based on load by VMs"""
        score = []
        for node in self.compute_model.get_all_compute_nodes().values():
            if node.status == element.ServiceState.ENABLED.value:
                self.number_of_enabled_nodes += 1

            instances = self.compute_model.get_node_instances(node)
            if len(instances) > 0:
                result = self.calculate_score_node(node)
                score.append((node.uuid, result))

        return score

    def node_and_instance_score(self, sorted_scores):
        """Get List of VMs from node"""
        node_to_release = sorted_scores[len(sorted_scores) - 1][0]
        instances = self.compute_model.get_node_instances(
            self.compute_model.get_node_by_uuid(node_to_release))

        instances_to_migrate = self.filter_instances_by_audit_tag(instances)
        instance_score = []
        for instance in instances_to_migrate:
            if instance.state == element.InstanceState.ACTIVE.value:
                instance_score.append(
                    (instance, self.calculate_score_instance(instance)))

        return node_to_release, instance_score

    def create_migration_instance(self, mig_instance, mig_source_node,
                                  mig_destination_node):
        """Create migration VM"""
        if self.compute_model.migrate_instance(
                mig_instance, mig_source_node, mig_destination_node):
            self.add_migration(mig_instance.uuid, 'live',
                               mig_source_node.uuid,
                               mig_destination_node.uuid)

        if len(self.compute_model.get_node_instances(mig_source_node)) == 0:
            self.add_change_service_state(mig_source_node.
                                          uuid,
                                          element.ServiceState.DISABLED.value)
            self.number_of_released_nodes += 1

    def calculate_num_migrations(self, sorted_instances, node_to_release,
                                 sorted_score):
        number_migrations = 0
        for mig_instance, __ in sorted_instances:
            for node_uuid, __ in sorted_score:
                mig_source_node = self.compute_model.get_node_by_uuid(
                    node_to_release)
                mig_destination_node = self.compute_model.get_node_by_uuid(
                    node_uuid)

                result = self.check_migration(
                    mig_source_node, mig_destination_node, mig_instance)
                if result:
                    self.create_migration_instance(
                        mig_instance, mig_source_node, mig_destination_node)
                    number_migrations += 1
                    break
        return number_migrations

    def unsuccessful_migration_actualization(self, number_migrations,
                                             unsuccessful_migration):
        if number_migrations > 0:
            self.number_of_migrations += number_migrations
            return 0
        else:
            return unsuccessful_migration + 1

    def pre_execute(self):
        LOG.info("Initializing Server Consolidation")

        if not self.compute_model:
            raise exception.ClusterStateNotDefined()

        if len(self.compute_model.get_all_compute_nodes()) == 0:
            raise exception.ClusterEmpty()

        if self.compute_model.stale:
            raise exception.ClusterStateStale()

        LOG.debug(self.compute_model.to_string())

    def do_execute(self):
        unsuccessful_migration = 0

        scores = self.compute_score_of_nodes()
        # Sort compute nodes by Score decreasing
        sorted_scores = sorted(scores, reverse=True, key=lambda x: (x[1]))
        LOG.debug("Compute node(s) BFD %s", sorted_scores)
        # Get Node to be released
        if len(scores) == 0:
            LOG.warning(
                "The workloads of the compute nodes"
                " of the cluster is zero")
            return

        while sorted_scores and (
                not self.migration_attempts or
                self.migration_attempts >= unsuccessful_migration):
            node_to_release, instance_score = self.node_and_instance_score(
                sorted_scores)

            # Sort instances by Score
            sorted_instances = sorted(
                instance_score, reverse=True, key=lambda x: (x[1]))
            # BFD: Best Fit Decrease
            LOG.debug("Instance(s) BFD %s", sorted_instances)

            migrations = self.calculate_num_migrations(
                sorted_instances, node_to_release, sorted_scores)

            unsuccessful_migration = self.unsuccessful_migration_actualization(
                migrations, unsuccessful_migration)

            if not migrations:
                # We don't have any possible migrations to perform on this node
                # so we discard the node so we can try to migrate instances
                # from the next one in the list
                sorted_scores.pop()

        infos = {
            "compute_nodes_count": self.number_of_enabled_nodes,
            "released_compute_nodes_count": self.number_of_released_nodes,
            "instance_migrations_count": self.number_of_migrations,
            "efficacy": self.efficacy
        }
        LOG.debug(infos)

    def post_execute(self):
        self.solution.set_efficacy_indicators(
            compute_nodes_count=self.number_of_enabled_nodes,
            released_compute_nodes_count=self.number_of_released_nodes,
            instance_migrations_count=self.number_of_migrations,
        )
        LOG.debug(self.compute_model.to_string())
