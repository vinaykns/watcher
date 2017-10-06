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

import random
import time

from oslo_log import log

import cinderclient.exceptions as ciexceptions
import glanceclient.exc as glexceptions
import novaclient.exceptions as nvexceptions

from watcher.common import clients
from watcher.common import exception
from watcher.common import utils

LOG = log.getLogger(__name__)


class NovaHelper(object):

    def __init__(self, osc=None):
        """:param osc: an OpenStackClients instance"""
        self.osc = osc if osc else clients.OpenStackClients()
        self.neutron = self.osc.neutron()
        self.cinder = self.osc.cinder()
        self.nova = self.osc.nova()
        self.glance = self.osc.glance()

    def get_compute_node_list(self):
        return self.nova.hypervisors.list()

    def get_compute_node_by_id(self, node_id):
        """Get compute node by ID (*not* UUID)"""
        # We need to pass an object with an 'id' attribute to make it work
        return self.nova.hypervisors.get(utils.Struct(id=node_id))

    def get_compute_node_by_hostname(self, node_hostname):
        """Get compute node by ID (*not* UUID)"""
        # We need to pass an object with an 'id' attribute to make it work
        try:
            compute_nodes = self.nova.hypervisors.search(node_hostname)
            if len(compute_nodes) != 1:
                raise exception.ComputeNodeNotFound(name=node_hostname)

            return self.get_compute_node_by_id(compute_nodes[0].id)
        except Exception as exc:
            LOG.exception(exc)
            raise exception.ComputeNodeNotFound(name=node_hostname)

    def get_instance_list(self):
        return self.nova.servers.list(search_opts={'all_tenants': True})

    def get_service(self, service_id):
        return self.nova.services.find(id=service_id)

    def get_flavor(self, flavor_id):
        return self.nova.flavors.get(flavor_id)

    def get_aggregate_list(self):
        return self.nova.aggregates.list()

    def get_aggregate_detail(self, aggregate_id):
        return self.nova.aggregates.get(aggregate_id)

    def get_availability_zone_list(self):
        return self.nova.availability_zones.list(detailed=True)

    def find_instance(self, instance_id):
        return self.nova.servers.get(instance_id)

    def confirm_resize(self, instance, previous_status, retry=60):
        instance.confirm_resize()
        instance = self.nova.servers.get(instance.id)
        while instance.status != previous_status and retry:
            instance = self.nova.servers.get(instance.id)
            retry -= 1
            time.sleep(1)
        if instance.status == previous_status:
            return True
        else:
            LOG.debug("confirm resize failed for the "
                      "instance %s" % instance.id)
            return False

    def wait_for_volume_status(self, volume, status, timeout=60,
                               poll_interval=1):
        """Wait until volume reaches given status.

        :param volume: volume resource
        :param status: expected status of volume
        :param timeout: timeout in seconds
        :param poll_interval: poll interval in seconds
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            volume = self.cinder.volumes.get(volume.id)
            if volume.status == status:
                break
            time.sleep(poll_interval)
        else:
            raise Exception("Volume %s did not reach status %s after %d s"
                            % (volume.id, status, timeout))
        return volume.status == status

    def watcher_non_live_migrate_instance(self, instance_id, dest_hostname,
                                          keep_original_image_name=True,
                                          retry=120):
        """This method migrates a given instance

        using an image of this instance and creating a new instance
        from this image. It saves some configuration information
        about the original instance : security group, list of networks,
        list of attached volumes, floating IP, ...
        in order to apply the same settings to the new instance.
        At the end of the process the original instance is deleted.
        It returns True if the migration was successful,
        False otherwise.

        if destination hostname not given, this method calls nova api
        to migrate the instance.

        :param instance_id: the unique id of the instance to migrate.
        :param keep_original_image_name: flag indicating whether the
            image name from which the original instance was built must be
            used as the name of the intermediate image used for migration.
            If this flag is False, a temporary image name is built
        """
        new_image_name = ""
        LOG.debug(
            "Trying a non-live migrate of instance '%s' " % instance_id)

        # Looking for the instance to migrate
        instance = self.find_instance(instance_id)
        if not instance:
            LOG.debug("Instance %s not found !" % instance_id)
            return False
        else:
            # NOTE: If destination node is None call Nova API to migrate
            # instance
            host_name = getattr(instance, "OS-EXT-SRV-ATTR:host")
            LOG.debug(
                "Instance %s found on host '%s'." % (instance_id, host_name))

            if dest_hostname is None:
                previous_status = getattr(instance, 'status')

                instance.migrate()
                instance = self.nova.servers.get(instance_id)
                while (getattr(instance, 'status') not in
                       ["VERIFY_RESIZE", "ERROR"] and retry):
                    instance = self.nova.servers.get(instance.id)
                    time.sleep(2)
                    retry -= 1
                new_hostname = getattr(instance, 'OS-EXT-SRV-ATTR:host')

                if (host_name != new_hostname and
                   instance.status == 'VERIFY_RESIZE'):
                    if not self.confirm_resize(instance, previous_status):
                        return False
                    LOG.debug(
                        "cold migration succeeded : "
                        "instance %s is now on host '%s'." % (
                            instance_id, new_hostname))
                    return True
                else:
                    LOG.debug(
                        "cold migration for instance %s failed" % instance_id)
                    return False

            if not keep_original_image_name:
                # randrange gives you an integral value
                irand = random.randint(0, 1000)

                # Building the temporary image name
                # which will be used for the migration
                new_image_name = "tmp-migrate-%s-%s" % (instance_id, irand)
            else:
                # Get the image name of the current instance.
                # We'll use the same name for the new instance.
                imagedict = getattr(instance, "image")
                image_id = imagedict["id"]
                image = self.glance.images.get(image_id)
                new_image_name = getattr(image, "name")

            instance_name = getattr(instance, "name")
            flavordict = getattr(instance, "flavor")
            # a_dict = dict([flavorstr.strip('{}').split(":"),])
            flavor_id = flavordict["id"]
            flavor = self.nova.flavors.get(flavor_id)
            flavor_name = getattr(flavor, "name")
            keypair_name = getattr(instance, "key_name")

            addresses = getattr(instance, "addresses")

            floating_ip = ""
            network_names_list = []

            for network_name, network_conf_obj in addresses.items():
                LOG.debug(
                    "Extracting network configuration for network '%s'" %
                    network_name)

                network_names_list.append(network_name)

                for net_conf_item in network_conf_obj:
                    if net_conf_item['OS-EXT-IPS:type'] == "floating":
                        floating_ip = net_conf_item['addr']
                        break

            sec_groups_list = getattr(instance, "security_groups")
            sec_groups = []

            for sec_group_dict in sec_groups_list:
                sec_groups.append(sec_group_dict['name'])

            # Stopping the old instance properly so
            # that no new data is sent to it and to its attached volumes
            stopped_ok = self.stop_instance(instance_id)

            if not stopped_ok:
                LOG.debug("Could not stop instance: %s" % instance_id)
                return False

            # Building the temporary image which will be used
            # to re-build the same instance on another target host
            image_uuid = self.create_image_from_instance(instance_id,
                                                         new_image_name)

            if not image_uuid:
                LOG.debug(
                    "Could not build temporary image of instance: %s" %
                    instance_id)
                return False

            #
            # We need to get the list of attached volumes and detach
            # them from the instance in order to attache them later
            # to the new instance
            #
            blocks = []

            # Looks like this :
            # os-extended-volumes:volumes_attached |
            # [{u'id': u'c5c3245f-dd59-4d4f-8d3a-89d80135859a'}]
            attached_volumes = getattr(instance,
                                       "os-extended-volumes:volumes_attached")

            for attached_volume in attached_volumes:
                volume_id = attached_volume['id']

                try:
                    volume = self.cinder.volumes.get(volume_id)

                    attachments_list = getattr(volume, "attachments")

                    device_name = attachments_list[0]['device']
                    # When a volume is attached to an instance
                    # it contains the following property :
                    # attachments = [{u'device': u'/dev/vdb',
                    # u'server_id': u'742cc508-a2f2-4769-a794-bcdad777e814',
                    # u'id': u'f6d62785-04b8-400d-9626-88640610f65e',
                    # u'host_name': None, u'volume_id':
                    # u'f6d62785-04b8-400d-9626-88640610f65e'}]

                    # boot_index indicates a number
                    # designating the boot order of the device.
                    # Use -1 for the boot volume,
                    # choose 0 for an attached volume.
                    block_device_mapping_v2_item = {"device_name": device_name,
                                                    "source_type": "volume",
                                                    "destination_type":
                                                        "volume",
                                                    "uuid": volume_id,
                                                    "boot_index": "0"}

                    blocks.append(
                        block_device_mapping_v2_item)

                    LOG.debug("Detaching volume %s from instance: %s" % (
                        volume_id, instance_id))
                    # volume.detach()
                    self.nova.volumes.delete_server_volume(instance_id,
                                                           volume_id)

                    if not self.wait_for_volume_status(volume, "available", 5,
                                                       10):
                        LOG.debug(
                            "Could not detach volume %s from instance: %s" % (
                                volume_id, instance_id))
                        return False
                except ciexceptions.NotFound:
                    LOG.debug("Volume '%s' not found " % image_id)
                    return False

            # We create the new instance from
            # the intermediate image of the original instance
            new_instance = self. \
                create_instance(dest_hostname,
                                instance_name,
                                image_uuid,
                                flavor_name,
                                sec_groups,
                                network_names_list=network_names_list,
                                keypair_name=keypair_name,
                                create_new_floating_ip=False,
                                block_device_mapping_v2=blocks)

            if not new_instance:
                LOG.debug(
                    "Could not create new instance "
                    "for non-live migration of instance %s" % instance_id)
                return False

            try:
                LOG.debug("Detaching floating ip '%s' from instance %s" % (
                    floating_ip, instance_id))
                # We detach the floating ip from the current instance
                instance.remove_floating_ip(floating_ip)

                LOG.debug(
                    "Attaching floating ip '%s' to the new instance %s" % (
                        floating_ip, new_instance.id))

                # We attach the same floating ip to the new instance
                new_instance.add_floating_ip(floating_ip)
            except Exception as e:
                LOG.debug(e)

            new_host_name = getattr(new_instance, "OS-EXT-SRV-ATTR:host")

            # Deleting the old instance (because no more useful)
            delete_ok = self.delete_instance(instance_id)
            if not delete_ok:
                LOG.debug("Could not delete instance: %s" % instance_id)
                return False

            LOG.debug(
                "Instance %s has been successfully migrated "
                "to new host '%s' and its new id is %s." % (
                    instance_id, new_host_name, new_instance.id))

            return True

    def resize_instance(self, instance_id, flavor, retry=120):
        """This method resizes given instance with specified flavor.

        This method uses the Nova built-in resize()
        action to do a resize of a given instance.

        It returns True if the resize was successful,
        False otherwise.

        :param instance_id: the unique id of the instance to resize.
        :param flavor: the name or ID of the flavor to resize to.
        """
        LOG.debug("Trying a resize of instance %s to flavor '%s'" % (
            instance_id, flavor))

        # Looking for the instance to resize
        instance = self.find_instance(instance_id)

        flavor_id = None

        try:
            flavor_id = self.nova.flavors.get(flavor)
        except nvexceptions.NotFound:
            flavor_id = [f.id for f in self.nova.flavors.list() if
                         f.name == flavor][0]
        except nvexceptions.ClientException as e:
            LOG.debug("Nova client exception occurred while resizing "
                      "instance %s. Exception: %s", instance_id, e)

        if not flavor_id:
            LOG.debug("Flavor not found: %s" % flavor)
            return False

        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return False

        instance_status = getattr(instance, 'OS-EXT-STS:vm_state')
        LOG.debug(
            "Instance %s is in '%s' status." % (instance_id,
                                                instance_status))

        instance.resize(flavor=flavor_id)
        while getattr(instance,
                      'OS-EXT-STS:vm_state') != 'resized' \
                and retry:
            instance = self.nova.servers.get(instance.id)
            LOG.debug(
                'Waiting the resize of {0}  to {1}'.format(
                    instance, flavor_id))
            time.sleep(1)
            retry -= 1

        instance_status = getattr(instance, 'status')
        if instance_status != 'VERIFY_RESIZE':
            return False

        instance.confirm_resize()

        LOG.debug("Resizing succeeded : instance %s is now on flavor "
                  "'%s'.", instance_id, flavor_id)

        return True

    def live_migrate_instance(self, instance_id, dest_hostname,
                              block_migration=False, retry=120):
        """This method does a live migration of a given instance

        This method uses the Nova built-in live_migrate()
        action to do a live migration of a given instance.

        It returns True if the migration was successful,
        False otherwise.

        :param instance_id: the unique id of the instance to migrate.
        :param dest_hostname: the name of the destination compute node, if
                              destination_node is None, nova scheduler choose
                              the destination host
        :param block_migration:  No shared storage is required.
        """
        LOG.debug("Trying to live migrate instance %s " % (instance_id))

        # Looking for the instance to migrate
        instance = self.find_instance(instance_id)
        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return False
        else:
            host_name = getattr(instance, 'OS-EXT-SRV-ATTR:host')
            LOG.debug(
                "Instance %s found on host '%s'." % (instance_id, host_name))

            instance.live_migrate(host=dest_hostname,
                                  block_migration=block_migration,
                                  disk_over_commit=True)

            instance = self.nova.servers.get(instance_id)

            # NOTE: If destination host is not specified for live migration
            # let nova scheduler choose the destination host.
            if dest_hostname is None:
                while (instance.status not in ['ACTIVE', 'ERROR'] and retry):
                    instance = self.nova.servers.get(instance.id)
                    LOG.debug(
                        'Waiting the migration of {0}'.format(instance.id))
                    time.sleep(1)
                    retry -= 1
                new_hostname = getattr(instance, 'OS-EXT-SRV-ATTR:host')

                if host_name != new_hostname and instance.status == 'ACTIVE':
                    LOG.debug(
                        "Live migration succeeded : "
                        "instance %s is now on host '%s'." % (
                            instance_id, new_hostname))
                    return True
                else:
                    return False

            while getattr(instance,
                          'OS-EXT-SRV-ATTR:host') != dest_hostname \
                    and retry:
                instance = self.nova.servers.get(instance.id)
                LOG.debug(
                    'Waiting the migration of {0}  to {1}'.format(
                        instance,
                        getattr(instance,
                                'OS-EXT-SRV-ATTR:host')))
                time.sleep(1)
                retry -= 1

            host_name = getattr(instance, 'OS-EXT-SRV-ATTR:host')
            if host_name != dest_hostname:
                return False

            LOG.debug(
                "Live migration succeeded : "
                "instance %s is now on host '%s'." % (
                    instance_id, host_name))

            return True

    def abort_live_migrate(self, instance_id, source, destination, retry=240):
        LOG.debug("Aborting live migration of instance %s" % instance_id)
        migration = self.get_running_migration(instance_id)
        if migration:
            migration_id = getattr(migration[0], "id")
            try:
                self.nova.server_migrations.live_migration_abort(
                    server=instance_id, migration=migration_id)
            except exception as e:
                # Note: Does not return from here, as abort request can't be
                # accepted but migration still going on.
                LOG.exception(e)
        else:
            LOG.debug(
                "No running migrations found for instance %s" % instance_id)

        while retry:
            instance = self.nova.servers.get(instance_id)
            if (getattr(instance, 'OS-EXT-STS:task_state') is None and
               getattr(instance, 'status') in ['ACTIVE', 'ERROR']):
                break
            time.sleep(2)
            retry -= 1
        instance_host = getattr(instance, 'OS-EXT-SRV-ATTR:host')
        instance_status = getattr(instance, 'status')

        # Abort live migration successfull, action is cancelled
        if instance_host == source and instance_status == 'ACTIVE':
            return True
        # Nova Unable to abort live migration, action is succeded
        elif instance_host == destination and instance_status == 'ACTIVE':
            return False

        else:
            raise Exception("Live migration execution and abort both failed "
                            "for the instance %s" % instance_id)

    def enable_service_nova_compute(self, hostname):
        if self.nova.services.enable(host=hostname,
                                     binary='nova-compute'). \
                status == 'enabled':
            return True
        else:
            return False

    def disable_service_nova_compute(self, hostname):
        if self.nova.services.disable(host=hostname,
                                      binary='nova-compute'). \
                status == 'disabled':
            return True
        else:
            return False

    def set_host_offline(self, hostname):
        # See API on http://developer.openstack.org/api-ref-compute-v2.1.html
        # especially the PUT request
        # regarding this resource : /v2.1/os-hosts/​{host_name}​
        #
        # The following body should be sent :
        # {
        # "host": {
        # "host": "65c5d5b7e3bd44308e67fc50f362aee6",
        # "maintenance_mode": "off_maintenance",
        # "status": "enabled"
        # }
        # }

        # Voir ici
        # https://github.com/openstack/nova/
        # blob/master/nova/virt/xenapi/host.py
        # set_host_enabled(self, enabled):
        # Sets the compute host's ability to accept new instances.
        # host_maintenance_mode(self, host, mode):
        # Start/Stop host maintenance window.
        # On start, it triggers guest instances evacuation.
        host = self.nova.hosts.get(hostname)

        if not host:
            LOG.debug("host not found: %s" % hostname)
            return False
        else:
            host[0].update(
                {"maintenance_mode": "disable", "status": "disable"})
            return True

    def create_image_from_instance(self, instance_id, image_name,
                                   metadata={"reason": "instance_migrate"}):
        """This method creates a new image from a given instance.

        It waits for this image to be in 'active' state before returning.
        It returns the unique UUID of the created image if successful,
        None otherwise.

        :param instance_id: the uniqueid of
            the instance to backup as an image.
        :param image_name: the name of the image to create.
        :param metadata: a dictionary containing the list of
            key-value pairs to associate to the image as metadata.
        """
        LOG.debug(
            "Trying to create an image from instance %s ..." % instance_id)

        # Looking for the instance
        instance = self.find_instance(instance_id)

        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return None
        else:
            host_name = getattr(instance, 'OS-EXT-SRV-ATTR:host')
            LOG.debug(
                "Instance %s found on host '%s'." % (instance_id, host_name))

            # We need to wait for an appropriate status
            # of the instance before we can build an image from it
            if self.wait_for_instance_status(instance, ('ACTIVE', 'SHUTOFF'),
                                             5,
                                             10):
                image_uuid = self.nova.servers.create_image(instance_id,
                                                            image_name,
                                                            metadata)

                image = self.glance.images.get(image_uuid)
                if not image:
                    return None

                # Waiting for the new image to be officially in ACTIVE state
                # in order to make sure it can be used
                status = image.status
                retry = 10
                while status != 'active' and status != 'error' and retry:
                    time.sleep(5)
                    retry -= 1
                    # Retrieve the instance again so the status field updates
                    image = self.glance.images.get(image_uuid)
                    if not image:
                        break
                    status = image.status
                    LOG.debug("Current image status: %s" % status)

                if not image:
                    LOG.debug("Image not found: %s" % image_uuid)
                else:
                    LOG.debug(
                        "Image %s successfully created for instance %s" % (
                            image_uuid, instance_id))
                    return image_uuid
        return None

    def delete_instance(self, instance_id):
        """This method deletes a given instance.

        :param instance_id: the unique id of the instance to delete.
        """
        LOG.debug("Trying to remove instance %s ..." % instance_id)

        instance = self.find_instance(instance_id)

        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return False
        else:
            self.nova.servers.delete(instance_id)
            LOG.debug("Instance %s removed." % instance_id)
            return True

    def suspend_instance(self, instance_id):
        instance = self.find_instance(instance_id)
        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return False
        else:
            self.nova.servers.suspend(instance_id)
            LOG.debug("Instance %s removed." % instance_id)
            return True

    def resume_instance(self, instance_id):
        instance = self.find_instance(instance_id)
        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return False
        else:
            self.nova.servers.resume(instance_id)
            return True

    def stop_instance(self, instance_id):
        """This method stops a given instance.

        :param instance_id: the unique id of the instance to stop.
        """
        LOG.debug("Trying to stop instance %s ..." % instance_id)

        instance = self.find_instance(instance_id)

        if not instance:
            LOG.debug("Instance not found: %s" % instance_id)
            return False
        elif getattr(instance, 'OS-EXT-STS:vm_state') == "stopped":
            LOG.debug("Instance has been stopped: %s" % instance_id)
            return True
        else:
            self.nova.servers.stop(instance_id)

            if self.wait_for_instance_state(instance, "stopped", 8, 10):
                LOG.debug("Instance %s stopped." % instance_id)
                return True
            else:
                return False

    def wait_for_instance_state(self, server, state, retry, sleep):
        """Waits for server to be in a specific state

        The state can be one of the following :
        active, stopped

        :param server: server object.
        :param state: for which state we are waiting for
        :param retry: how many times to retry
        :param sleep: seconds to sleep between the retries
        """
        if not server:
            return False

        while getattr(server, 'OS-EXT-STS:vm_state') != state and retry:
            time.sleep(sleep)
            server = self.nova.servers.get(server)
            retry -= 1
        return getattr(server, 'OS-EXT-STS:vm_state') == state

    def wait_for_instance_status(self, instance, status_list, retry, sleep):
        """Waits for instance to be in a specific status

        The status can be one of the following
        : BUILD, ACTIVE, ERROR, VERIFY_RESIZE, SHUTOFF

        :param instance: instance object.
        :param status_list: tuple containing the list of
            status we are waiting for
        :param retry: how many times to retry
        :param sleep: seconds to sleep between the retries
        """
        if not instance:
            return False

        while instance.status not in status_list and retry:
            LOG.debug("Current instance status: %s" % instance.status)
            time.sleep(sleep)
            instance = self.nova.servers.get(instance.id)
            retry -= 1
        LOG.debug("Current instance status: %s" % instance.status)
        return instance.status in status_list

    def create_instance(self, node_id, inst_name="test", image_id=None,
                        flavor_name="m1.tiny",
                        sec_group_list=["default"],
                        network_names_list=["demo-net"], keypair_name="mykeys",
                        create_new_floating_ip=True,
                        block_device_mapping_v2=None):
        """This method creates a new instance

        It also creates, if requested, a new floating IP and associates
        it with the new instance
        It returns the unique id of the created instance.
        """
        LOG.debug(
            "Trying to create new instance '%s' "
            "from image '%s' with flavor '%s' ..." % (
                inst_name, image_id, flavor_name))

        try:
            self.nova.keypairs.findall(name=keypair_name)
        except nvexceptions.NotFound:
            LOG.debug("Key pair '%s' not found " % keypair_name)
            return

        try:
            image = self.glance.images.get(image_id)
        except glexceptions.NotFound:
            LOG.debug("Image '%s' not found " % image_id)
            return

        try:
            flavor = self.nova.flavors.find(name=flavor_name)
        except nvexceptions.NotFound:
            LOG.debug("Flavor '%s' not found " % flavor_name)
            return

        # Make sure all security groups exist
        for sec_group_name in sec_group_list:
            try:
                self.nova.security_groups.find(name=sec_group_name)

            except nvexceptions.NotFound:
                LOG.debug("Security group '%s' not found " % sec_group_name)
                return

        net_list = list()

        for network_name in network_names_list:
            nic_id = self.get_network_id_from_name(network_name)

            if not nic_id:
                LOG.debug("Network '%s' not found " % network_name)
                return
            net_obj = {"net-id": nic_id}
            net_list.append(net_obj)

        # get availability zone of destination host
        azone = self.nova.services.list(host=node_id,
                                        binary='nova-compute')[0].zone
        instance = self.nova.servers.create(
            inst_name, image,
            flavor=flavor,
            key_name=keypair_name,
            security_groups=sec_group_list,
            nics=net_list,
            block_device_mapping_v2=block_device_mapping_v2,
            availability_zone="%s:%s" % (azone, node_id))

        # Poll at 5 second intervals, until the status is no longer 'BUILD'
        if instance:
            if self.wait_for_instance_status(instance,
                                             ('ACTIVE', 'ERROR'), 5, 10):
                instance = self.nova.servers.get(instance.id)

                if create_new_floating_ip and instance.status == 'ACTIVE':
                    LOG.debug(
                        "Creating a new floating IP"
                        " for instance '%s'" % instance.id)
                    # Creating floating IP for the new instance
                    floating_ip = self.nova.floating_ips.create()

                    instance.add_floating_ip(floating_ip)

                    LOG.debug("Instance %s associated to Floating IP '%s'" % (
                        instance.id, floating_ip.ip))

        return instance

    def get_network_id_from_name(self, net_name="private"):
        """This method returns the unique id of the provided network name"""
        networks = self.neutron.list_networks(name=net_name)

        # LOG.debug(networks)
        network_id = networks['networks'][0]['id']

        return network_id

    def get_instance_by_uuid(self, instance_uuid):
        return [instance for instance in
                self.nova.servers.list(search_opts={"all_tenants": True,
                                                    "uuid": instance_uuid})]

    def get_instance_by_name(self, instance_name):
        return [instance for instance in
                self.nova.servers.list(search_opts={"all_tenants": True,
                                                    "name": instance_name})]

    def get_instances_by_node(self, host):
        return [instance for instance in
                self.nova.servers.list(search_opts={"all_tenants": True})
                if self.get_hostname(instance) == host]

    def get_hostname(self, instance):
        return str(getattr(instance, 'OS-EXT-SRV-ATTR:host'))

    def get_flavor_instance(self, instance, cache):
        fid = instance.flavor['id']
        if fid in cache:
            flavor = cache.get(fid)
        else:
            try:
                flavor = self.nova.flavors.get(fid)
            except ciexceptions.NotFound:
                flavor = None
            cache[fid] = flavor
        attr_defaults = [('name', 'unknown-id-%s' % fid),
                         ('vcpus', 0), ('ram', 0), ('disk', 0),
                         ('ephemeral', 0), ('extra_specs', {})]
        for attr, default in attr_defaults:
            if not flavor:
                instance.flavor[attr] = default
                continue
            instance.flavor[attr] = getattr(flavor, attr, default)

    def get_running_migration(self, instance_id):
        return self.nova.server_migrations.list(server=instance_id)

    def swap_volume(self, old_volume, new_volume,
                    retry=120, retry_interval=10):
        """Swap old_volume for new_volume"""
        attachments = old_volume.attachments
        instance_id = attachments[0]['server_id']
        # do volume update
        self.nova.volumes.update_server_volume(
            instance_id, old_volume.id, new_volume.id)
        while getattr(new_volume, 'status') != 'in-use' and retry:
            new_volume = self.cinder.volumes.get(new_volume.id)
            LOG.debug('Waiting volume update to {0}'.format(new_volume))
            time.sleep(retry_interval)
            retry -= 1
            LOG.debug("retry count: %s" % retry)
        if getattr(new_volume, 'status') != "in-use":
            LOG.error("Volume update retry timeout or error")
            return False

        host_name = getattr(new_volume, "os-vol-host-attr:host")
        LOG.debug(
            "Volume update succeeded : "
            "Volume %s is now on host '%s'." % (new_volume.id, host_name))
        return True
