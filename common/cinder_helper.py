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

import time

from oslo_log import log

from cinderclient import exceptions as cinder_exception
from cinderclient.v2.volumes import Volume
from watcher._i18n import _
from watcher.common import clients
from watcher.common import exception
from watcher import conf

CONF = conf.CONF
LOG = log.getLogger(__name__)


class CinderHelper(object):

    def __init__(self, osc=None):
        """:param osc: an OpenStackClients instance"""
        self.osc = osc if osc else clients.OpenStackClients()
        self.cinder = self.osc.cinder()

    def get_storage_node_list(self):
        return list(self.cinder.services.list(binary='cinder-volume'))

    def get_storage_node_by_name(self, name):
        """Get storage node by name(host@backendname)"""
        try:
            storages = list(filter(lambda storage:
                            storage.host == name,
                            self.get_storage_node_list()))
            if len(storages) != 1:
                raise exception.StorageNodeNotFound(name=name)
            return storages[0]
        except Exception as exc:
            LOG.exception(exc)
            raise exception.StorageNodeNotFound(name=name)

    def get_storage_pool_list(self):
        return self.cinder.pools.list(detailed=True)

    def get_storage_pool_by_name(self, name):
        """Get pool by name(host@backend#poolname)"""
        try:
            pools = list(filter(lambda pool:
                         pool.name == name,
                         self.get_storage_pool_list()))
            if len(pools) != 1:
                raise exception.PoolNotFound(name=name)
            return pools[0]
        except Exception as exc:
            LOG.exception(exc)
            raise exception.PoolNotFound(name=name)

    def get_volume_list(self):
        return self.cinder.volumes.list(search_opts={'all_tenants': True})

    def get_volume_type_list(self):
        return self.cinder.volume_types.list()

    def get_volume_type_by_backendname(self, backendname):
        volume_type_list = self.get_volume_type_list()

        volume_type = list(filter(
            lambda volume_type:
                volume_type.extra_specs.get(
                    'volume_backend_name') == backendname, volume_type_list))
        if volume_type:
            return volume_type[0].name
        else:
            return ""

    def get_volume(self, volume):

        if isinstance(volume, Volume):
            volume = volume.id

        try:
            volume = self.cinder.volumes.get(volume)
            return volume
        except cinder_exception.NotFound:
            return self.cinder.volumes.find(name=volume)

    def backendname_from_poolname(self, poolname):
        """Get backendname from poolname"""
        # pooolname formatted as host@backend#pool since ocata
        # as of ocata, may as only host
        backend = poolname.split('#')[0]
        backendname = ""
        try:
            backendname = backend.split('@')[1]
        except IndexError:
            pass
        return backendname

    def _has_snapshot(self, volume):
        """Judge volume has a snapshot"""
        volume = self.get_volume(volume)
        if volume.snapshot_id:
            return True
        return False

    def can_cold(self, volume, host=None):
        """Judge volume can be migrated"""
        can_cold = False
        status = self.get_volume(volume).status
        snapshot = self._has_snapshot(volume)

        same_host = False
        if host and getattr(volume, 'os-vol-host-attr:host') == host:
            same_host = True

        if (status == 'available' and
                snapshot is False and
                same_host is False):
            can_cold = True

        return can_cold

    def get_deleting_volume(self, volume):
        volume = self.get_volume(volume)
        all_volume = self.get_volume_list()
        for _volume in all_volume:
            if getattr(_volume, 'os-vol-mig-status-attr:name_id') == volume.id:
                return _volume
        return False

    def _can_get_volume(self, volume_id):
        """Check to get volume with volume_id"""
        try:
            volume = self.get_volume(volume_id)
            if not volume:
                raise Exception
        except cinder_exception.NotFound:
            return False
        else:
            return True

    def check_volume_deleted(self, volume, retry=120, retry_interval=10):
        """Check volume has been deleted"""
        volume = self.get_volume(volume)
        while self._can_get_volume(volume.id) and retry:
            volume = self.get_volume(volume.id)
            time.sleep(retry_interval)
            retry -= 1
            LOG.debug("retry count: %s" % retry)
            LOG.debug("Waiting to complete deletion of volume %s" % volume.id)
        if self._can_get_volume(volume.id):
            LOG.error("Volume deletion error: %s" % volume.id)
            return False

        LOG.debug("Volume %s was deleted successfully." % volume.id)
        return True

    def check_migrated(self, volume, retry_interval=10):
        volume = self.get_volume(volume)
        while getattr(volume, 'migration_status') == 'migrating':
            volume = self.get_volume(volume.id)
            LOG.debug('Waiting the migration of {0}'.format(volume))
            time.sleep(retry_interval)
            if getattr(volume, 'migration_status') == 'error':
                host_name = getattr(volume, 'os-vol-host-attr:host')
                error_msg = (("Volume migration error : "
                             "volume %(volume)s is now on host '%(host)s'.") %
                             {'volume': volume.id, 'host': host_name})
                LOG.error(error_msg)
                return False

        host_name = getattr(volume, 'os-vol-host-attr:host')
        if getattr(volume, 'migration_status') == 'success':
            # check original volume deleted
            deleting_volume = self.get_deleting_volume(volume)
            if deleting_volume:
                delete_id = getattr(deleting_volume, 'id')
                if not self.check_volume_deleted(delete_id):
                    return False
        else:
            host_name = getattr(volume, 'os-vol-host-attr:host')
            error_msg = (("Volume migration error : "
                         "volume %(volume)s is now on host '%(host)s'.") %
                         {'volume': volume.id, 'host': host_name})
            LOG.error(error_msg)
            return False
        LOG.debug(
            "Volume migration succeeded : "
            "volume %s is now on host '%s'." % (
                volume.id, host_name))
        return True

    def migrate(self, volume, dest_node):
        """Migrate volume to dest_node"""
        volume = self.get_volume(volume)
        dest_backend = self.backendname_from_poolname(dest_node)
        dest_type = self.get_volume_type_by_backendname(dest_backend)
        if volume.volume_type != dest_type:
            raise exception.Invalid(
                message=(_("Volume type must be same for migrating")))

        source_node = getattr(volume, 'os-vol-host-attr:host')
        LOG.debug("Volume %s found on host '%s'."
                  % (volume.id, source_node))

        self.cinder.volumes.migrate_volume(
            volume, dest_node, False, True)

        return self.check_migrated(volume)

    def retype(self, volume, dest_type):
        """Retype volume to dest_type with on-demand option"""
        volume = self.get_volume(volume)
        if volume.volume_type == dest_type:
            raise exception.Invalid(
                message=(_("Volume type must be different for retyping")))

        source_node = getattr(volume, 'os-vol-host-attr:host')
        LOG.debug(
            "Volume %s found on host '%s'." % (
                volume.id, source_node))

        self.cinder.volumes.retype(
            volume, dest_type, "on-demand")

        return self.check_migrated(volume)

    def create_volume(self, cinder, volume,
                      dest_type, retry=120, retry_interval=10):
        """Create volume of volume with dest_type using cinder"""
        volume = self.get_volume(volume)
        LOG.debug("start creating new volume")
        new_volume = cinder.volumes.create(
            getattr(volume, 'size'),
            name=getattr(volume, 'name'),
            volume_type=dest_type,
            availability_zone=getattr(volume, 'availability_zone'))
        while getattr(new_volume, 'status') != 'available' and retry:
            new_volume = cinder.volumes.get(new_volume.id)
            LOG.debug('Waiting volume creation of {0}'.format(new_volume))
            time.sleep(retry_interval)
            retry -= 1
            LOG.debug("retry count: %s" % retry)

        if getattr(new_volume, 'status') != 'available':
            error_msg = (_("Failed to create volume '%(volume)s. ") %
                         {'volume': new_volume.id})
            raise Exception(error_msg)

        LOG.debug("Volume %s was created successfully." % new_volume)
        return new_volume

    def delete_volume(self, volume):
        """Delete volume"""
        volume = self.get_volume(volume)
        self.cinder.volumes.delete(volume)
        result = self.check_volume_deleted(volume)
        if not result:
            error_msg = (_("Failed to delete volume '%(volume)s. ") %
                         {'volume': volume.id})
            raise Exception(error_msg)
