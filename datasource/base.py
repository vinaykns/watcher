
import abc
import six

from watcher.common import clients 
from monascaclient import exc



@six.add_metaclass(abc.ABCMeta)
class BaseDriver(object):
    def __init__(self, osc=None):
        self.osc = osc if osc else clients.OpenstackClients()
        
