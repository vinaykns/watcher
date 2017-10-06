# -*- encoding: utf-8 -*-
# Copyright 2017 NEC Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import six

from oslo_log import log

from watcher.common import cinder_helper
from watcher.common import exception
from watcher.decision_engine.model.collector import base
from watcher.decision_engine.model import element
from watcher.decision_engine.model import model_root
from watcher.decision_engine.model.notification import cinder

LOG = log.getLogger(__name__)


class CinderClusterDataModelCollector(base.BaseClusterDataModelCollector):
    """Cinder cluster data model collector

    The Cinder cluster data model collector creates an in-memory
    representation of the resources exposed by the storage service.
    """

    def __init__(self, config, osc=None):
        super(CinderClusterDataModelCollector, self).__init__(config, osc)

    @property
    def notification_endpoints(self):
        """Associated notification endpoints

        :return: Associated notification endpoints
        :rtype: List of :py:class:`~.EventsNotificationEndpoint` instances
        """
        return [
            cinder.CapacityNotificationEndpoint(self),
            cinder.VolumeCreateEnd(self),
            cinder.VolumeDeleteEnd(self),
            cinder.VolumeUpdateEnd(self),
            cinder.VolumeAttachEnd(self),
            cinder.VolumeDetachEnd(self),
            cinder.VolumeResizeEnd(self)
        ]

    def execute(self):
        """Build the storage cluster data model"""
        LOG.debug("Building latest Cinder cluster data model")

        builder = ModelBuilder(self.osc)
        return builder.execute()


class ModelBuilder(object):
    """Build the graph-based model

    This model builder adds the following data"
    - Storage-related knowledge (Cinder)

    """
    def __init__(self, osc):
        self.osc = osc
        self.model = model_root.StorageModelRoot()
        self.cinder = osc.cinder()
        self.cinder_helper = cinder_helper.CinderHelper(osc=self.osc)

    def _add_physical_layer(self):
        """Add the physical layer of the graph.

        This includes components which represent actual infrastructure
        hardware.
        """
        for snode in self.cinder_helper.get_storage_node_list():
            self.add_storage_node(snode)
        for pool in self.cinder_helper.get_storage_pool_list():
            pool = self._build_storage_pool(pool)
            self.model.add_pool(pool)
            storage_name = getattr(pool, 'name')
            try:
                storage_node = self.model.get_node_by_name(
                    storage_name)
                # Connect the instance to its compute node
                self.model.map_pool(pool, storage_node)
            except exception.StorageNodeNotFound:
                continue

    def add_storage_node(self, node):
        # Build and add base node.
        storage_node = self.build_storage_node(node)
        self.model.add_node(storage_node)

    def add_storage_pool(self, pool):
        storage_pool = self._build_storage_pool(pool)
        self.model.add_pool(storage_pool)

    def build_storage_node(self, node):
        """Build a storage node from a Cinder storage node

        :param node: A storage node
        :type node: :py:class:`~cinderclient.v2.services.Service`
        """
        # node.host is formatted as host@backendname since ocata,
        # or may be only host as of ocata
        backend = ""
        try:
            backend = node.host.split('@')[1]
        except IndexError:
            pass

        volume_type = self.cinder_helper.get_volume_type_by_backendname(
            backend)

        # build up the storage node.
        node_attributes = {
            "host": node.host,
            "zone": node.zone,
            "state": node.state,
            "status": node.status,
            "volume_type": volume_type}

        storage_node = element.StorageNode(**node_attributes)
        return storage_node

    def _build_storage_pool(self, pool):
        """Build a storage pool from a Cinder storage pool

        :param pool: A storage pool
        :type pool: :py:class:`~cinderlient.v2.capabilities.Capabilities`
        """
        # build up the storage pool.
        node_attributes = {
            "name": pool.name,
            "total_volumes": pool.total_volumes,
            "total_capacity_gb": pool.total_capacity_gb,
            "free_capacity_gb": pool.free_capacity_gb,
            "provisioned_capacity_gb": pool.provisioned_capacity_gb,
            "allocated_capacity_gb": pool.allocated_capacity_gb}

        storage_pool = element.Pool(**node_attributes)
        return storage_pool

    def _add_virtual_layer(self):
        """Add the virtual layer to the graph.

        This layer is the virtual components of the infrastructure.
        """
        self._add_virtual_storage()

    def _add_virtual_storage(self):
        volumes = self.cinder_helper.get_volume_list()
        for vol in volumes:
            volume = self._build_volume_node(vol)
            self.model.add_volume(volume)
            pool_name = getattr(vol, 'os-vol-host-attr:host')
            if pool_name is None:
                # The volume is not attached to any pool
                continue
            try:
                pool = self.model.get_pool_by_pool_name(
                    pool_name)
                self.model.map_volume(volume, pool)
            except exception.PoolNotFound:
                continue

    def _build_volume_node(self, volume):
        """Build an volume node

        Create an volume node for the graph using cinder and the
        `volume` cinder object.
        :param instance: Cinder Volume object.
        :return: A volume node for the graph.
        """
        attachments = [{k: v for k, v in six.iteritems(d) if k in (
            'server_id', 'attachment_id')} for d in volume.attachments]

        volume_attributes = {
            "uuid": volume.id,
            "size": volume.size,
            "status": volume.status,
            "attachments": attachments,
            "name": volume.name or "",
            "multiattach": volume.multiattach,
            "snapshot_id": volume.snapshot_id or "",
            "project_id": getattr(volume, 'os-vol-tenant-attr:tenant_id'),
            "metadata": volume.metadata,
            "bootable": volume.bootable}

        return element.Volume(**volume_attributes)

    def execute(self):
        """Instantiates the graph with the openstack cluster data.

        The graph is populated along 2 layers: virtual and physical. As each
        new layer is built connections are made back to previous layers.
        """
        self._add_physical_layer()
        self._add_virtual_layer()
        return self.model
