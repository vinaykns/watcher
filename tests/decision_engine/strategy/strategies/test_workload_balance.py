# -*- encoding: utf-8 -*-
# Copyright (c) 2016 Intel Corp
#
# Authors: Junjie-Huang <junjie.huang@intel.com>
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
import collections
import datetime
import mock

from watcher.applier.loading import default
from watcher.common import exception
from watcher.common import utils
from watcher.decision_engine.model import model_root
from watcher.decision_engine.strategy import strategies
from watcher.tests import base
from watcher.tests.decision_engine.model import ceilometer_metrics
from watcher.tests.decision_engine.model import faker_cluster_state
from watcher.tests.decision_engine.model import gnocchi_metrics


class TestWorkloadBalance(base.TestCase):

    scenarios = [
        ("Ceilometer",
         {"datasource": "ceilometer",
          "fake_datasource_cls": ceilometer_metrics.FakeCeilometerMetrics}),
        ("Gnocchi",
         {"datasource": "gnocchi",
          "fake_datasource_cls": gnocchi_metrics.FakeGnocchiMetrics}),
    ]

    def setUp(self):
        super(TestWorkloadBalance, self).setUp()
        # fake metrics
        self.fake_metrics = self.fake_datasource_cls()
        # fake cluster
        self.fake_cluster = faker_cluster_state.FakerModelCollector()

        p_model = mock.patch.object(
            strategies.WorkloadBalance, "compute_model",
            new_callable=mock.PropertyMock)
        self.m_model = p_model.start()
        self.addCleanup(p_model.stop)

        p_datasource = mock.patch.object(
            strategies.WorkloadBalance, self.datasource,
            new_callable=mock.PropertyMock)
        self.m_datasource = p_datasource.start()
        self.addCleanup(p_datasource.stop)

        p_audit_scope = mock.patch.object(
            strategies.WorkloadBalance, "audit_scope",
            new_callable=mock.PropertyMock
        )
        self.m_audit_scope = p_audit_scope.start()
        self.addCleanup(p_audit_scope.stop)

        self.m_audit_scope.return_value = mock.Mock()
        self.m_datasource.return_value = mock.Mock(
            statistic_aggregation=self.fake_metrics.mock_get_statistics_wb)
        self.strategy = strategies.WorkloadBalance(
            config=mock.Mock(datasource=self.datasource))
        self.strategy.input_parameters = utils.Struct()
        self.strategy.input_parameters.update({'threshold': 25.0,
                                               'period': 300})
        self.strategy.threshold = 25.0
        self.strategy._period = 300

    def test_calc_used_resource(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        node = model.get_node_by_uuid('Node_0')
        cores_used, mem_used, disk_used = (
            self.strategy.calculate_used_resource(node))

        self.assertEqual((cores_used, mem_used, disk_used), (20, 4, 40))

    def test_group_hosts_by_cpu_util(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        self.strategy.threshold = 30
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        self.assertEqual(n1[0]['node'].uuid, 'Node_0')
        self.assertEqual(n2[0]['node'].uuid, 'Node_1')
        self.assertEqual(avg, 8.0)

    def test_choose_instance_to_migrate(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        instance_to_mig = self.strategy.choose_instance_to_migrate(
            n1, avg, w_map)
        self.assertEqual(instance_to_mig[0].uuid, 'Node_0')
        self.assertEqual(instance_to_mig[1].uuid,
                         "73b09e16-35b7-4922-804e-e8f5d9b740fc")

    def test_choose_instance_notfound(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        instances = model.get_all_instances()
        [model.remove_instance(inst) for inst in instances.values()]
        instance_to_mig = self.strategy.choose_instance_to_migrate(
            n1, avg, w_map)
        self.assertIsNone(instance_to_mig)

    def test_filter_destination_hosts(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        self.strategy.datasource = mock.MagicMock(
            statistic_aggregation=self.fake_metrics.mock_get_statistics_wb)
        n1, n2, avg, w_map = self.strategy.group_hosts_by_cpu_util()
        instance_to_mig = self.strategy.choose_instance_to_migrate(
            n1, avg, w_map)
        dest_hosts = self.strategy.filter_destination_hosts(
            n2, instance_to_mig[1], avg, w_map)
        self.assertEqual(len(dest_hosts), 1)
        self.assertEqual(dest_hosts[0]['node'].uuid, 'Node_1')

    def test_exception_model(self):
        self.m_model.return_value = None
        self.assertRaises(
            exception.ClusterStateNotDefined, self.strategy.execute)

    def test_exception_cluster_empty(self):
        model = model_root.ModelRoot()
        self.m_model.return_value = model
        self.assertRaises(exception.ClusterEmpty, self.strategy.execute)

    def test_exception_stale_cdm(self):
        self.fake_cluster.set_cluster_data_model_as_stale()
        self.m_model.return_value = self.fake_cluster.cluster_data_model

        self.assertRaises(
            exception.ClusterStateNotDefined,
            self.strategy.execute)

    def test_execute_cluster_empty(self):
        model = model_root.ModelRoot()
        self.m_model.return_value = model
        self.assertRaises(exception.ClusterEmpty, self.strategy.execute)

    def test_execute_no_workload(self):
        model = self.fake_cluster.generate_scenario_4_with_1_node_no_instance()
        self.m_model.return_value = model
        solution = self.strategy.execute()
        self.assertEqual([], solution.actions)

    def test_execute(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        solution = self.strategy.execute()
        actions_counter = collections.Counter(
            [action.get('action_type') for action in solution.actions])

        num_migrations = actions_counter.get("migrate", 0)
        self.assertEqual(num_migrations, 1)

    def test_check_parameters(self):
        model = self.fake_cluster.generate_scenario_6_with_2_nodes()
        self.m_model.return_value = model
        solution = self.strategy.execute()
        loader = default.DefaultActionLoader()
        for action in solution.actions:
            loaded_action = loader.load(action['action_type'])
            loaded_action.input_parameters = action['input_parameters']
            loaded_action.validate_parameters()

    def test_periods(self):
        model = self.fake_cluster.generate_scenario_1()
        self.m_model.return_value = model
        p_ceilometer = mock.patch.object(
            strategies.WorkloadBalance, "ceilometer")
        m_ceilometer = p_ceilometer.start()
        self.addCleanup(p_ceilometer.stop)
        p_gnocchi = mock.patch.object(strategies.WorkloadBalance, "gnocchi")
        m_gnocchi = p_gnocchi.start()
        self.addCleanup(p_gnocchi.stop)
        datetime_patcher = mock.patch.object(
            datetime, 'datetime',
            mock.Mock(wraps=datetime.datetime)
        )
        mocked_datetime = datetime_patcher.start()
        mocked_datetime.utcnow.return_value = datetime.datetime(
            2017, 3, 19, 18, 53, 11, 657417)
        self.addCleanup(datetime_patcher.stop)
        m_ceilometer.statistic_aggregation = mock.Mock(
            side_effect=self.fake_metrics.mock_get_statistics_wb)
        m_gnocchi.statistic_aggregation = mock.Mock(
            side_effect=self.fake_metrics.mock_get_statistics_wb)
        instance0 = model.get_instance_by_uuid("INSTANCE_0")
        self.strategy.group_hosts_by_cpu_util()
        if self.strategy.config.datasource == "ceilometer":
            m_ceilometer.statistic_aggregation.assert_any_call(
                aggregate='avg', meter_name='cpu_util',
                period=300, resource_id=instance0.uuid)
        elif self.strategy.config.datasource == "gnocchi":
            stop_time = datetime.datetime.utcnow()
            start_time = stop_time - datetime.timedelta(
                seconds=int('300'))
            m_gnocchi.statistic_aggregation.assert_called_with(
                resource_id=mock.ANY, metric='cpu_util',
                granularity=300, start_time=start_time, stop_time=stop_time,
                aggregation='mean')
