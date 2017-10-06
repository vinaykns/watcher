# -*- encoding: utf-8 -*-
#
# Authors: Vojtech CIMA <cima@zhaw.ch>
#          Bruno GRAZIOLI <gaea@zhaw.ch>
#          Sean MURPHY <murp@zhaw.ch>
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

import os

import mock

from watcher.decision_engine.model.collector import base
from watcher.decision_engine.model import model_root as modelroot


class FakerModelCollector(base.BaseClusterDataModelCollector):

    def __init__(self, config=None, osc=None):
        if config is None:
            config = mock.Mock()
        super(FakerModelCollector, self).__init__(config)

    @property
    def notification_endpoints(self):
        return []

    def execute(self):
        return self.generate_scenario_1()

    def load_data(self, filename):
        cwd = os.path.abspath(os.path.dirname(__file__))
        data_folder = os.path.join(cwd, "data")

        with open(os.path.join(data_folder, filename), 'rb') as xml_file:
            xml_data = xml_file.read()

        return xml_data

    def load_model(self, filename):
        return modelroot.ModelRoot.from_xml(self.load_data(filename))

    def generate_scenario_1(self):
        """Simulates cluster with 2 nodes and 2 instances using 1:1 mapping"""
        return self.load_model('scenario_1_with_metrics.xml')

    def generate_scenario_2(self):
        """Simulates a cluster

        With 4 nodes and 6 instances all mapped to a single node
        """
        return self.load_model('scenario_2_with_metrics.xml')

    def generate_scenario_3(self):
        """Simulates a cluster

        With 4 nodes and 6 instances all mapped to one node
        """
        return self.load_model('scenario_3_with_metrics.xml')

    def generate_scenario_4(self):
        """Simulates a cluster

        With 4 nodes and 6 instances spread on all nodes
        """
        return self.load_model('scenario_4_with_metrics.xml')


class FakeCeilometerMetrics(object):
    def __init__(self, model):
        self.model = model

    def mock_get_statistics(self, resource_id, meter_name, period=3600,
                            aggregate='avg'):
        if meter_name == "compute.node.cpu.percent":
            return self.get_node_cpu_util(resource_id)
        elif meter_name == "cpu_util":
            return self.get_instance_cpu_util(resource_id)
        elif meter_name == "memory.usage":
            return self.get_instance_ram_util(resource_id)
        elif meter_name == "disk.root.size":
            return self.get_instance_disk_root_size(resource_id)

    def get_node_cpu_util(self, r_id):
        """Calculates node utilization dynamicaly.

        node CPU utilization should consider
        and corelate with actual instance-node mappings
        provided within a cluster model.
        Returns relative node CPU utilization <0, 100>.
        :param r_id: resource id
        """
        node_uuid = '%s_%s' % (r_id.split('_')[0], r_id.split('_')[1])
        node = self.model.get_node_by_uuid(node_uuid)
        instances = self.model.get_node_instances(node)
        util_sum = 0.0
        for instance_uuid in instances:
            instance = self.model.get_instance_by_uuid(instance_uuid)
            total_cpu_util = instance.vcpus * self.get_instance_cpu_util(
                instance.uuid)
            util_sum += total_cpu_util / 100.0
        util_sum /= node.vcpus
        return util_sum * 100.0

    @staticmethod
    def get_instance_cpu_util(r_id):
        instance_cpu_util = dict()
        instance_cpu_util['INSTANCE_0'] = 10
        instance_cpu_util['INSTANCE_1'] = 30
        instance_cpu_util['INSTANCE_2'] = 60
        instance_cpu_util['INSTANCE_3'] = 20
        instance_cpu_util['INSTANCE_4'] = 40
        instance_cpu_util['INSTANCE_5'] = 50
        instance_cpu_util['INSTANCE_6'] = 100
        instance_cpu_util['INSTANCE_7'] = 100
        instance_cpu_util['INSTANCE_8'] = 100
        instance_cpu_util['INSTANCE_9'] = 100
        return instance_cpu_util[str(r_id)]

    @staticmethod
    def get_instance_ram_util(r_id):
        instance_ram_util = dict()
        instance_ram_util['INSTANCE_0'] = 1
        instance_ram_util['INSTANCE_1'] = 2
        instance_ram_util['INSTANCE_2'] = 4
        instance_ram_util['INSTANCE_3'] = 8
        instance_ram_util['INSTANCE_4'] = 3
        instance_ram_util['INSTANCE_5'] = 2
        instance_ram_util['INSTANCE_6'] = 1
        instance_ram_util['INSTANCE_7'] = 2
        instance_ram_util['INSTANCE_8'] = 4
        instance_ram_util['INSTANCE_9'] = 8
        return instance_ram_util[str(r_id)]

    @staticmethod
    def get_instance_disk_root_size(r_id):
        instance_disk_util = dict()
        instance_disk_util['INSTANCE_0'] = 10
        instance_disk_util['INSTANCE_1'] = 15
        instance_disk_util['INSTANCE_2'] = 30
        instance_disk_util['INSTANCE_3'] = 35
        instance_disk_util['INSTANCE_4'] = 20
        instance_disk_util['INSTANCE_5'] = 25
        instance_disk_util['INSTANCE_6'] = 25
        instance_disk_util['INSTANCE_7'] = 25
        instance_disk_util['INSTANCE_8'] = 25
        instance_disk_util['INSTANCE_9'] = 25
        return instance_disk_util[str(r_id)]


class FakeGnocchiMetrics(object):
    def __init__(self, model):
        self.model = model

    def mock_get_statistics(self, resource_id, metric, granularity,
                            start_time, stop_time, aggregation='mean'):
        if metric == "compute.node.cpu.percent":
            return self.get_node_cpu_util(resource_id)
        elif metric == "cpu_util":
            return self.get_instance_cpu_util(resource_id)
        elif metric == "memory.usage":
            return self.get_instance_ram_util(resource_id)
        elif metric == "disk.root.size":
            return self.get_instance_disk_root_size(resource_id)

    def get_node_cpu_util(self, r_id):
        """Calculates node utilization dynamicaly.

        node CPU utilization should consider
        and corelate with actual instance-node mappings
        provided within a cluster model.
        Returns relative node CPU utilization <0, 100>.

        :param r_id: resource id
        """
        node_uuid = '%s_%s' % (r_id.split('_')[0], r_id.split('_')[1])
        node = self.model.get_node_by_uuid(node_uuid)
        instances = self.model.get_node_instances(node)
        util_sum = 0.0
        for instance_uuid in instances:
            instance = self.model.get_instance_by_uuid(instance_uuid)
            total_cpu_util = instance.vcpus * self.get_instance_cpu_util(
                instance.uuid)
            util_sum += total_cpu_util / 100.0
        util_sum /= node.vcpus
        return util_sum * 100.0

    @staticmethod
    def get_instance_cpu_util(r_id):
        instance_cpu_util = dict()
        instance_cpu_util['INSTANCE_0'] = 10
        instance_cpu_util['INSTANCE_1'] = 30
        instance_cpu_util['INSTANCE_2'] = 60
        instance_cpu_util['INSTANCE_3'] = 20
        instance_cpu_util['INSTANCE_4'] = 40
        instance_cpu_util['INSTANCE_5'] = 50
        instance_cpu_util['INSTANCE_6'] = 100
        instance_cpu_util['INSTANCE_7'] = 100
        instance_cpu_util['INSTANCE_8'] = 100
        instance_cpu_util['INSTANCE_9'] = 100
        return instance_cpu_util[str(r_id)]

    @staticmethod
    def get_instance_ram_util(r_id):
        instance_ram_util = dict()
        instance_ram_util['INSTANCE_0'] = 1
        instance_ram_util['INSTANCE_1'] = 2
        instance_ram_util['INSTANCE_2'] = 4
        instance_ram_util['INSTANCE_3'] = 8
        instance_ram_util['INSTANCE_4'] = 3
        instance_ram_util['INSTANCE_5'] = 2
        instance_ram_util['INSTANCE_6'] = 1
        instance_ram_util['INSTANCE_7'] = 2
        instance_ram_util['INSTANCE_8'] = 4
        instance_ram_util['INSTANCE_9'] = 8
        return instance_ram_util[str(r_id)]

    @staticmethod
    def get_instance_disk_root_size(r_id):
        instance_disk_util = dict()
        instance_disk_util['INSTANCE_0'] = 10
        instance_disk_util['INSTANCE_1'] = 15
        instance_disk_util['INSTANCE_2'] = 30
        instance_disk_util['INSTANCE_3'] = 35
        instance_disk_util['INSTANCE_4'] = 20
        instance_disk_util['INSTANCE_5'] = 25
        instance_disk_util['INSTANCE_6'] = 25
        instance_disk_util['INSTANCE_7'] = 25
        instance_disk_util['INSTANCE_8'] = 25
        instance_disk_util['INSTANCE_9'] = 25
        return instance_disk_util[str(r_id)]
