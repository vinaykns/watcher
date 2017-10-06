# -*- encoding: utf-8 -*-
# Copyright (c) 2017 ZTE Corporation
#
# Authors: licanwei <li.canwei2@zte.com.cn>
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

import random

from oslo_log import log

from watcher._i18n import _
from watcher.common import exception as wexc
from watcher.decision_engine.strategy.strategies import base

LOG = log.getLogger(__name__)


class SavingEnergy(base.SavingEnergyBaseStrategy):

    def __init__(self, config, osc=None):

        super(SavingEnergy, self).__init__(config, osc)
        self._ironic_client = None
        self._nova_client = None

        self.with_vms_node_pool = []
        self.free_poweron_node_pool = []
        self.free_poweroff_node_pool = []
        self.free_used_percent = 0
        self.min_free_hosts_num = 1

    @property
    def ironic_client(self):
        if not self._ironic_client:
            self._ironic_client = self.osc.ironic()
        return self._ironic_client

    @property
    def nova_client(self):
        if not self._nova_client:
            self._nova_client = self.osc.nova()
        return self._nova_client

    @classmethod
    def get_name(cls):
        return "saving_energy"

    @classmethod
    def get_display_name(cls):
        return _("Saving Energy Strategy")

    @classmethod
    def get_translatable_display_name(cls):
        return "Saving Energy Strategy"

    @classmethod
    def get_schema(cls):
        """return a schema of two input parameters

        The standby nodes refer to those nodes unused
        but still poweredon to deal with boom of new instances.
        """
        return {
            "properties": {
                "free_used_percent": {
                    "description": ("a rational number, which describes the"
                                    "quotient of"
                                    " min_free_hosts_num/nodes_with_VMs_num"
                                    "where nodes_with_VMs_num is the number"
                                    "of nodes with VMs"),
                    "type": "number",
                    "default": 10.0
                },
                "min_free_hosts_num": {
                    "description": ("minimum number of hosts without VMs"
                                    "but still powered on"),
                    "type": "number",
                    "default": 1
                },
            },
        }

    def add_action_poweronoff_node(self, node_uuid, state):
        """Add an action for node disability into the solution.

        :param node: node uuid
        :param state: node power state, power on or power off
        :return: None
        """
        params = {'state': state}
        self.solution.add_action(
            action_type='change_node_power_state',
            resource_id=node_uuid,
            input_parameters=params)

    def get_hosts_pool(self):
        """Get three pools, with_vms_node_pool, free_poweron_node_pool,

        free_poweroff_node_pool.

        """

        node_list = self.ironic_client.node.list()
        for node in node_list:
            node_uuid = (node.to_dict())['uuid']
            node_info = self.ironic_client.node.get(node_uuid).to_dict()
            hypervisor_id = node_info['extra'].get('compute_node_id', None)
            if hypervisor_id is None:
                LOG.warning(('Cannot find compute_node_id in extra '
                             'of ironic node %s'), node_uuid)
                continue
            hypervisor_node = self.nova_client.hypervisors.get(hypervisor_id)
            if hypervisor_node is None:
                LOG.warning(('Cannot find hypervisor %s'), hypervisor_id)
                continue
            hypervisor_node = hypervisor_node.to_dict()
            compute_service = hypervisor_node.get('service', None)
            host_uuid = compute_service.get('host')
            if not self.compute_model.get_node_by_uuid(host_uuid):
                continue

            if not (hypervisor_node.get('state') == 'up'):
                """filter nodes that are not in 'up' state"""
                continue
            else:
                if (hypervisor_node['running_vms'] == 0):
                    if (node_info['power_state'] == 'power on'):
                        self.free_poweron_node_pool.append(node_uuid)
                    elif (node_info['power_state'] == 'power off'):
                        self.free_poweroff_node_pool.append(node_uuid)
                else:
                    self.with_vms_node_pool.append(node_uuid)

    def save_energy(self):

        need_poweron = max(
            (len(self.with_vms_node_pool) * self.free_used_percent / 100), (
                self.min_free_hosts_num))
        len_poweron = len(self.free_poweron_node_pool)
        len_poweroff = len(self.free_poweroff_node_pool)
        if len_poweron > need_poweron:
            for node in random.sample(self.free_poweron_node_pool,
                                      (len_poweron - need_poweron)):
                self.add_action_poweronoff_node(node, 'off')
                LOG.debug("power off %s", node)
        elif len_poweron < need_poweron:
            diff = need_poweron - len_poweron
            for node in random.sample(self.free_poweroff_node_pool,
                                      min(len_poweroff, diff)):
                self.add_action_poweronoff_node(node, 'on')
                LOG.debug("power on %s", node)

    def pre_execute(self):
        """Pre-execution phase

        This can be used to fetch some pre-requisites or data.
        """
        LOG.info("Initializing Saving Energy Strategy")

        if not self.compute_model:
            raise wexc.ClusterStateNotDefined()

        if self.compute_model.stale:
            raise wexc.ClusterStateStale()

        LOG.debug(self.compute_model.to_string())

    def do_execute(self):
        """Strategy execution phase

        This phase is where you should put the main logic of your strategy.
        """
        self.free_used_percent = self.input_parameters.free_used_percent
        self.min_free_hosts_num = self.input_parameters.min_free_hosts_num

        self.get_hosts_pool()
        self.save_energy()

    def post_execute(self):
        """Post-execution phase

        This can be used to compute the global efficacy
        """
        self.solution.model = self.compute_model

        LOG.debug(self.compute_model.to_string())
