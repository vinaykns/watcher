# -*- encoding: utf-8 -*-
# Copyright (c) 2015 b<>com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from oslo_config import cfg
from oslo_utils import timeutils

from watcher.common import clients
from watcher.datasource import monasca as monasca_helper
from watcher.tests import base

CONF = cfg.CONF


@mock.patch.object(clients.OpenStackClients, 'monasca')
class TestMonascaHelper(base.BaseTestCase):

    def test_monasca_statistic_aggregation(self, mock_monasca):
        monasca = mock.MagicMock()
        expected_result = [{
            'columns': ['timestamp', 'avg'],
            'dimensions': {
                'hostname': 'rdev-indeedsrv001',
                'service': 'monasca'},
            'id': '0',
            'name': 'cpu.percent',
            'statistics': [
                ['2016-07-29T12:45:00Z', 0.0],
                ['2016-07-29T12:50:00Z', 0.9100000000000001],
                ['2016-07-29T12:55:00Z', 0.9111111111111112]]}]

        monasca.metrics.list_statistics.return_value = expected_result
        mock_monasca.return_value = monasca

        helper = monasca_helper.MonascaHelper()
        result = helper.statistic_aggregation(
            meter_name='cpu.percent',
            dimensions={'hostname': 'NODE_UUID'},
            start_time=timeutils.parse_isotime("2016-06-06T10:33:22.063176"),
            end_time=None,
            period=7200,
            aggregate='avg',
            group_by='*',
        )
        self.assertEqual(expected_result, result)

    def test_monasca_statistic_list(self, mock_monasca):
        monasca = mock.MagicMock()
        expected_result = [{
            'columns': ['timestamp', 'value', 'value_meta'],
            'dimensions': {
                'hostname': 'rdev-indeedsrv001',
                'service': 'monasca'},
            'id': '0',
            'measurements': [
                ['2016-07-29T12:54:06.000Z', 0.9, {}],
                ['2016-07-29T12:54:36.000Z', 0.9, {}],
                ['2016-07-29T12:55:06.000Z', 0.9, {}],
                ['2016-07-29T12:55:36.000Z', 0.8, {}]],
            'name': 'cpu.percent'}]

        monasca.metrics.list_measurements.return_value = expected_result
        mock_monasca.return_value = monasca
        helper = monasca_helper.MonascaHelper()
        val = helper.statistics_list(meter_name="cpu.percent", dimensions={})
        self.assertEqual(expected_result, val)

    def test_monasca_statistic_list_query_retry(self, mock_monasca):
        monasca = mock.MagicMock()
        expected_result = [{
            'columns': ['timestamp', 'value', 'value_meta'],
            'dimensions': {
                'hostname': 'rdev-indeedsrv001',
                'service': 'monasca'},
            'id': '0',
            'measurements': [
                ['2016-07-29T12:54:06.000Z', 0.9, {}],
                ['2016-07-29T12:54:36.000Z', 0.9, {}],
                ['2016-07-29T12:55:06.000Z', 0.9, {}],
                ['2016-07-29T12:55:36.000Z', 0.8, {}]],
            'name': 'cpu.percent'}]

        monasca.metrics.list_measurements.side_effect = [expected_result]
        mock_monasca.return_value = monasca
        helper = monasca_helper.MonascaHelper()
        val = helper.statistics_list(meter_name="cpu.percent", dimensions={})
        self.assertEqual(expected_result, val)
