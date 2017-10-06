# -*- encoding: utf-8 -*-
# Copyright (c) 2017 b<>com
#
# Authors: Vincent FRANCOISE <Vincent.FRANCOISE@b-com.com>
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

from watcher.decision_engine.model import element
from watcher.tests import base


class TestElement(base.TestCase):

    scenarios = [
        ("ComputeNode_with_all_fields", dict(
            cls=element.Instance,
            data={
                'uuid': 'FAKE_UUID',
                'state': 'state',
                'hostname': 'hostname',
                'human_id': 'human_id',
                'memory': 111,
                'vcpus': 222,
                'disk': 333,
                'disk_capacity': 444,
            })),
        ("ComputeNode_with_some_fields", dict(
            cls=element.Instance,
            data={
                'uuid': 'FAKE_UUID',
                'state': 'state',
                'vcpus': 222,
                'disk': 333,
                'disk_capacity': 444,
            })),
        ("Instance_with_all_fields", dict(
            cls=element.Instance,
            data={
                'uuid': 'FAKE_UUID',
                'state': 'state',
                'hostname': 'hostname',
                'human_id': 'human_id',
                'memory': 111,
                'vcpus': 222,
                'disk': 333,
                'disk_capacity': 444,
            })),
        ("Instance_with_some_fields", dict(
            cls=element.Instance,
            data={
                'uuid': 'FAKE_UUID',
                'state': 'state',
                'vcpus': 222,
                'disk': 333,
                'disk_capacity': 444,
            })),
    ]

    def test_as_xml_element(self):
        el = self.cls(**self.data)
        el.as_xml_element()


class TestStorageElement(base.TestCase):

    scenarios = [
        ("StorageNode_with_all_fields", dict(
            cls=element.StorageNode,
            data={
                'host': 'host@backend',
                'zone': 'zone',
                'status': 'enabled',
                'state': 'up',
                'volume_type': 'volume_type',
            })),
        ("Pool_with_all_fields", dict(
            cls=element.Pool,
            data={
                'name': 'host@backend#pool',
                'total_volumes': 1,
                'total_capacity_gb': 500,
                'free_capacity_gb': 420,
                'provisioned_capacity_gb': 80,
                'allocated_capacity_gb': 80,
                'virtual_free': 420,
            })),
        ("Pool_without_virtual_free_fields", dict(
            cls=element.Pool,
            data={
                'name': 'host@backend#pool',
                'total_volumes': 1,
                'total_capacity_gb': 500,
                'free_capacity_gb': 420,
                'provisioned_capacity_gb': 80,
                'allocated_capacity_gb': 80,
            })),
        ("Volume_with_all_fields", dict(
            cls=element.Volume,
            data={
                'uuid': 'FAKE_UUID',
                'size': 1,
                'status': 'in-use',
                'attachments': '[{"key": "value"}]',
                'name': 'name',
                'multiattach': 'false',
                'snapshot_id': '',
                'project_id': 'project_id',
                'metadata': '{"key": "value"}',
                'bootable': 'false',
                'human_id': 'human_id',
            })),
        ("Volume_without_bootable_fields", dict(
            cls=element.Volume,
            data={
                'uuid': 'FAKE_UUID',
                'size': 1,
                'status': 'in-use',
                'attachments': '[]',
                'name': 'name',
                'multiattach': 'false',
                'snapshot_id': '',
                'project_id': 'project_id',
                'metadata': '{"key": "value"}',
                'human_id': 'human_id',
            })),
        ("Volume_without_human_id_fields", dict(
            cls=element.Volume,
            data={
                'uuid': 'FAKE_UUID',
                'size': 1,
                'status': 'in-use',
                'attachments': '[]',
                'name': 'name',
                'multiattach': 'false',
                'snapshot_id': '',
                'project_id': 'project_id',
                'metadata': '{"key": "value"}',
            })),
    ]

    def test_as_xml_element(self):
        el = self.cls(**self.data)
        el.as_xml_element()
