#!/usr/bin/env python

import os
import os.path
import asyncio

from pydispatch import dispatcher

from openzwave.option import ZWaveOption
from openzwave.network import ZWaveNetwork

import qth

"""
Properties to expose for each ZWave Node.

NODE_PROPERTIES = {propname: (description, None or conversion_fn), ...}
"""
NODE_PROPERTIES = {
    "product_name": ("Product name of the node.", None),
    "product_type": ("Product type of the node.", None),
    "product_id": ("ZWave product ID of the node.", None),
    "device_type": ("ZWave device type of the node.", None),
    "role": ("ZWave device type of the node.", None),
    "capabilities": ("List of ZWave device "
                    "capabilities supported "
                    "by the node.", list),
    "neighbours": ("List of ZWave node IDs within range.", list),
    "command_classes": ("List of ZWave command classes supported.", list),
    "manufacturer_id": ("ZWave manufacturer ID type of the node.", None),
    "manufacturer_name": ("Manufacturer name of the node.", None),
    "generic": ("ZWave generic type of the node.", None),
    "basic": ("ZWave basic type of the node.", None),
    "specific": ("ZWave specific type of the node.", None),
    "security": ("ZWave security type of the node.", None),
    "version": ("ZWave version of the node.", None),
    "is_listening_device": ("Is a ZWave listening device.", None),
    "is_beaming_device": ("Is a ZWave beaming device.", None),
    "is_frequent_listening_device": ("Is a ZWave frequent listening device.", None),
    "is_security_device": ("Is a ZWave security device.", None),
    "is_routing_device": ("Is a ZWave routing device.", None),
    "is_zwave_plus": ("Supports the ZWave+ protocol extensions.", None),
    "is_locked": ("Is the node locked.", None),
    "is_sleeping": ("Is the node in a sleep state.", None),
    "max_baud_rate": ("The node's maximum baudrate.", None),
    "is_awake": ("Is the node in a non-sleep state.", None),
    "is_failed": ("Has the node failed/become unavailable.", None),
    "query_stage": ("Is the node in the ZWave query stage of initialisation.", None),
    "is_ready": ("Is the node ready.", None),
    "is_info_received": ("Has the ZWave node information been received.", None),
    "type": ("The type of ZWave node.", None),
}

"""
Properties to expose for each ZWave Value.
"""
VALUE_PROPERTIES = {
    "id_on_network": ("System-wide unique ZWave ID of the value.", None),
    "units": ("Units used for this value.", None),
    "max": ("Maximum value.", None),
    "min": ("Minimum value.", None),
    "type": ("ZWave value type specification.", None),
    "genre": ("Is this a Basic, User, Config or System value?", None),
    "index": ("The ZWave command class index.", None),
    "data": ("The value's... value!", None),
    "data_as_string": ("The value as a string.", None),
    "data_items": ("Possible values when a List type value.", list),
    "is_set": ("True if the value reported was sent from the device", None),
    "is_read_only": ("Is the value read-only.", None),
    "is_write_only": ("Is the value write-only.", None),
    "is_polled": ("Is the device polled?", None),
    "command_class": ("The ZWave command class.", None),
    "precision": ("The precision of the value", None),
}


"""
Names an descriptions of all events which can be triggered on a Node.
"""
NODE_EVENTS = {
    "heal": "Send the ZWave 'heal' command to the node. If the value is "
            "truthy, also updates routes.",
    "assign_return_route": "Request a Node re-find its return route to the "
                           "controller.",
    "refresh_info": "Request an update of all ZWave info.",
    "request_state": "Trigger fetching of dynamic ZWave info (e.g. values).",
    "neighbour_update": "Request a node update its neighbour tables.",
    "request_all_config_params": "Request known config params be fetched "
                                 "from the node.",
    "request_config_param": "Request a particular config parameter be reported.",
    "set_config_param": "Set a particular config parameter to a new value. "
                        "Takes an array of 2 or 3 arguments: the param ID, "
                        "value and optionally the size in bytes",
}


class QthZwave(object):
    
    def __init__(self, zwave_config_path, zwave_user_path,
                 zwave_device="/dev/ttyACM0",
                 qth_base_path="sys/zwave/",
                 host="localhost", port=1883, keepalive=10):
        self._loop = asyncio.get_event_loop()
        self._qth_base_path = qth_base_path
        self._client = qth.Client("Qth-Zwave-Bridge",
                                  "Exposes Z-wave devices via Qth.",
                                  loop=self._loop, host=host, port=port,
                                  kee=allow=keepalive)
        
        # For each node, gives the last knwon value of each of its properties
        # which are exposed by Qth. These values are updated periodically and
        # when changed the value is published via Qth.
        #
        # self._node_properties = {node_id: {propname: last_value, ...}, ...}
        self._node_properties = {}
        
        # For each node, gives the registered Qth callback for all events
        # registered for that node.
        #
        # self._node_events = {node_id: {eventname: cb_func, ...}, ...}
        self._node_events = {}
        
        # For each value, the callback setup to watch for changes
        #
        # self._value_properties = {node_id: {value_id: cb, ...}, ...}
        self._value_properties = {}
        
        options = ZWaveOption(device,
                              config_path=zwave_config_path,
                              user_path=zwave_user_path,
                              cmd_line="")
        options.set_log_file(os.path.join(zwave_user_path, "zwave.log"))
        options.set_append_log_file(True)
        options.set_console_output(True)
        options.set_save_log_level("Warning")
        options.set_logging(True)
        options.lock()
        
        self._network = ZWaveNetwork(options, autostart=False)
        
        for state in [ZWaveNetwork.SIGNAL_NETWORK_FAILED,
                      ZWaveNetwork.SIGNAL_NETWORK_STARTED,
                      ZWaveNetwork.SIGNAL_NETWORK_READY,
                      ZWaveNetwork.SIGNAL_NETWORK_STOPPED,
                      ZWaveNetwork.SIGNAL_NETWORK_RESETTED,
                      ZWaveNetwork.SIGNAL_NETWORK_AWAKED]:
            dispatcher.connect(
                self._make_network_state_change_callback(state),
                state)
        
        dispatcher.connect(self._on_node_added,
            ZWaveNetwork.SIGNAL_NODE_ADDED)
        dispatcher.connect(self._on_node_removed,
            ZWaveNetwork.SIGNAL_NODE_REMOVED)
        
        dispatcher.connect(self._on_value_added,
            ZWaveNetwork.SIGNAL_VALUE_ADDED)
        dispatcher.connect(self._on_value_changed,
            ZWaveNetwork.SIGNAL_VALUE_CHANGED)
        dispatcher.connect(self._on_value_removed,
            ZWaveNetwork.SIGNAL_VALUE_REMOVED)
        
        self._network.start()
    
    def _make_network_state_change_callback(self, state):
        """
        Create a callback to set the network_state property upon a change in
        zwave network state.
        """
        def cb(*args, **kwargs):
            self._loop.create_task(
                self._client.set(
                    self._qth_base_path + "network_state",
                    state[len("Network"):]))
        return cb
    
    def _node_path(self. node_id):
        return "{}nodes/{}/".format(self._qth_base_path, node_id)
    
    def _value_path(self. node_id, value_id):
        label = self._network.nodes[node_id].values[value_id].label
        return "{}nodes/{}/values/{}-{}".format(self._qth_base_path, node_id, label, value_id)
    
    def _update_node_properties(self, node_id, node):
        """
        Update the Qth published properties for a Node. If ``node`` is None,
        removes the properties entirely.
        """
        node_path = self._node_path(node_id)
        
        if node_id not in self._node_properties:
            self._node_properties[node_id] = {}
        
        if node is not None:
            properties = self._node_properties[node_id]
            for name, (description, convert) in NODE_PROPERTIES.items():
                # Register if required
                if name not in properties:
                    self._loop.create_task(self._client.register(
                        node_path + name,
                        description,
                        qth.PROPERTY_MANY_TO_ONE))
                
                # Update value if required
                value = getattr(self._network.nodes[node_id], name)
                if convert:
                    value = convert(value)
                if name not in properties or properties[name] != value:
                    self._loop.create_task(self._client.set_property(
                        node_path + name, value))
                properties[name] = value
        else:
            # Unregister all properties if node is None
            old_properties = self._node_properties.pop(node_id)
            for name in old_properties:
                self._loop.create_task(self._client.unreigster(node_path + name))
                self._loop.create_task(self._client.delete_property(node_path + name))
    
    def _setup_node_events(self, node_id):
        """Add callback handlers for all events."""
        node_path = self._node_path(node_id)
        
        if node_id not in self._node_events:
            events = {}
            self._node_events[node_id] = events
            
            for name, description in NODE_EVENTS.items():
                self._loop.create_task(self._client.register(
                    node_path + name, description, qth.EVENT_MANY_TO_ONE))
                events[name] = partial(getattr(self, "_on_{}".format(name)), node_id)
                self._loop.create_task(self._client.watch_event(
                    node_path + name, events[name]))
    
    def _remove_node_events(self, node_id):
        """Remove callbacks and registrations for all events."""
        node_path = self._node_path(node_id)
        
        if node_id not in self._node_events:
            for name, callback in self._node_events.pop(node_id).items():
                self._loop.create_task(self._client.unregister(node_path + name))
                self._loop.create_task(self._client.unwatch_event(
                    node_path + name, callback))
    
    def _on_node_added(self, node, *args, **kwargs):
        node_path = self._node_path(node.node_id)
        
        self._update_node_properties(node.node_id, node)
        self._setup_node_events(node.node_id)
    
    def _on_heal(self, node_id, _topic, arg):
        self._network.nodes[node_id].heal(bool(arg))
    
    def _on_assign_return_route(self, node_id, _topic, _arg):
        self._network.nodes[node_id].assign_return_route()
    
    def _on_refresh_info(self, node_id, _topic, _arg):
        self._network.nodes[node_id].refresh_info()
    
    def _on_request_state(self, node_id, _topic, _arg):
        self._network.nodes[node_id].request_state()
    
    def _on_neighbour_update(self, node_id, _topic, _arg):
        self._network.nodes[node_id].neighbour_update()
    
    def _on_request_all_config_params(self, node_id, _topic, _arg):
        # TODO: Setup reporting of this parameter ID? Comes via Values
        # somehow...
        self._network.nodes[node_id].request_all_config_params()
    
    def _on_request_config_param(self, node_id, _topic, arg):
        # TODO: Setup reporting of this parameter ID? Comes via Values
        # somehow...
        self._network.nodes[node_id].request_config_param(arg)
    
    def _on_set_config_param(self, node_id, _topic, arg):
        self._network.nodes[node_id].set_config_param(*arg)
    
    def _on_node_removed(self, node, *args, **kwargs):
        self._update_node_properties(node.node_id, None)
    
    
    
    def _on_value_added(self, node, value, *args, **kwargs):
        pass  # TODO
    
    def _on_value_changed(self, *args, **kwargs):
        pass  # TODO
    
    def _on_value_removed(self, *args, **kwargs):
        pass  # TODO
