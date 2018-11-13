#!/usr/bin/env python

import re
import os
import os.path
import asyncio
import functools
import json

from pydispatch import dispatcher

from openzwave.option import ZWaveOption
from openzwave.network import ZWaveNetwork

import qth

from .version import __version__

def normalise_value_label(label, used_labels=set()):
    """
    Given the label of a ZWave value, convert this into a space- and
    punctuation-free all-lowercase equivalent.
    """
    label = re.sub(r"[^\w]+", "-", label).strip("-").lower()
    if label not in used_labels:
        return label
    else:
        num = 2
        while "{}{}".format(label, num) in used_labels:
            num += 1
        return "{}{}".format(label, num)


class Value(object):
    """
    Logic which keeps a ZWave value object in sync with its Qth interface.
    """
    def __init__(self, client, loop, ozw_network, ozw_value, qth_base_path, used_labels):
        self._client = client
        self._loop = loop
        self._ozw_network = ozw_network
        self._ozw_value = ozw_value
        
        self._is_initialised = asyncio.Event(loop=self._loop)
        
        self._label = normalise_value_label(self._ozw_value.label, used_labels)
        used_labels.add(self._label)
        
        self._value_path = (
            qth_base_path +
            "values/{}".format(self._label))
        self._units_path = "{}/units".format(self._value_path)
        self._refresh_path = "{}/refresh".format(self._value_path)

        # Values reported by zwave and set in Qth which we expect to shortly
        # receive echoed back from Qth (and we should ignore)
        self._expected_values = []
        
        # The last value received/sent from/to Qth. This will (should!) never
        # be qth.Empty so this simply acts as a sentinel to cause the value to
        # be set immediately during the call to on_zwave_value_changed called
        # by init_async.
        self._last_qth_value = qth.Empty
        
        # Last units written to Qth
        self._last_qth_units = qth.Empty
    
    async def init_async(self):
        """
        Complete registration of the value. Must be called after instantiation.
        """
        try:
            await asyncio.wait([
                self._client.register(
                    self._value_path,
                    qth.PROPERTY_MANY_TO_ONE,
                    "The value of the value.",
                    delete_on_unregister=True),
                self._client.register(
                    self._units_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "The units this value is expressed in.",
                    delete_on_unregister=True),
                self._client.register(
                    self._refresh_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Triggers a refresh of this value"),
                self.on_zwave_value_changed(),
                self._client.watch_property(self._value_path,
                                            self._on_qth_value_set),
                self._client.watch_event(self._refresh_path,
                                         self._on_refresh),
            ], loop=self._loop)
        finally:
            self._is_initialised.set()
    
    async def remove(self):
        """
        Unregister this value from Qth.
        """
        await self._is_initialised.wait()
        
        # NB: Do this first to avoid receiving the deletion callback
        await self._client.unwatch_property(self._value_path,
                                            self._on_qth_value_set)
        
        await asyncio.wait([
            self._client.unregister(self._value_path),
            self._client.unregister(self._units_path),
            self._client.unregister(self._refresh_path),
            self._client.delete_property(self._value_path),
            self._client.delete_property(self._units_path),
            self._client.unwatch_event(self._refresh_path, self._on_refresh),
        ], loop=self._loop)
    
    async def _on_refresh(self, _topic, _value):
        """Called when the refresh event is sent."""
        self._ozw_value.refresh()
    
    async def on_zwave_value_changed(self):
        """Called when the ZWave value reports a change."""
        value = self._ozw_value.data
        if value != self._last_qth_value:
            self._last_qth_value = value
            self._expected_values.append(value)
            await self._client.set_property(self._value_path, value)
        
        units = self._ozw_value.units
        if units != self._last_qth_units:
            self._last_qth_units = units
            await self._client.set_property(self._units_path, units)
    
    async def _on_qth_value_set(self, _topic, value):
        """Called when the Qth value/set event is sent."""
        if value in self._expected_values:
            self._expected_values.remove(value)
        else:
            if not self._ozw_value.is_read_only:
                checked_value = self._ozw_value.check_data(value)
            else:
                checked_value = None
            
            if checked_value is not None and checked_value == value:
                # Value is valid, set that
                self._ozw_value.data = checked_value
                self._last_qth_value = value
            elif checked_value is not None:
                # Value is not valid, but has been converted to a valid value,
                # re-set the Qth value and when that callback arrives, set the
                # OZW value.
                await self._client.set_property(self._value_path,
                                                checked_value)
            else:
                # Value is not valid, revert to previous value
                self._expected_values.append(self._last_qth_value)
                await self._client.set_property(self._value_path,
                                                self._last_qth_value)


class Node(object):
    """
    Logic which keeps a ZWave node object in sync with its Qth interface.
    """
    def __init__(self, client, loop, ozw_network, ozw_node, qth_base_path):
        self._client = client
        self._loop = loop
        self._ozw_network = ozw_network
        self._ozw_node = ozw_node
        
        self._used_value_labels = set()
        
        self._is_initialised = asyncio.Event(loop=self._loop)
        
        self._qth_base_path = (qth_base_path +
                               "nodes/{}/".format(self._ozw_node.node_id))
        
        self._is_failed_path = self._qth_base_path + "is_failed"
        self._manufacturer_id_path = self._qth_base_path + "manufacturer_id"
        self._manufacturer_name_path = self._qth_base_path + "manufacturer_name"
        self._neighbours_path = self._qth_base_path + "neighbours"
        self._product_id_path = self._qth_base_path + "product_id"
        self._product_name_path = self._qth_base_path + "product_name"
        self._product_type_path = self._qth_base_path + "product_type"
        self._heal_path = self._qth_base_path + "heal"
        self._set_config_param_path = self._qth_base_path + "set_config_param"
        self._remove_failed_node_path = self._qth_base_path + "remove_failed_node"
        
        # {ozw.ZWaveValue: Value, ...}
        self._values = {}
    
    async def init_async(self):
        """
        Complete registration of the node. Must be called after instantiation.
        """
        try:
            await asyncio.wait([
                self._client.register(
                    self._is_failed_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "Boolean. True if the device has been marked as failed by the "
                    "ZWave controller.",
                    delete_on_unregister=True),
                self._client.register(
                    self._manufacturer_id_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "String. The hex representation of the ZWave manufacturer ID.",
                    delete_on_unregister=True),
                self._client.register(
                    self._manufacturer_name_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "String. The manufacturer's name.",
                    delete_on_unregister=True),
                self._client.register(
                    self._neighbours_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "Array of Integers. The Node IDs of other nodes visible from "
                    "this node.",
                    delete_on_unregister=True),
                self._client.register(
                    self._product_id_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "String. The hex representation of the ZWave product ID.",
                    delete_on_unregister=True),
                self._client.register(
                    self._product_name_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "String. The product name.",
                    delete_on_unregister=True),
                self._client.register(
                    self._product_type_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "String. The ZWave product type code.",
                    delete_on_unregister=True),
                self._client.register(
                    self._heal_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Send this event to attempt to trigger the node healing "
                    "process."),
                self._client.register(
                    self._set_config_param_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Send this event to attempt set a config parameter on a ZWave "
                    "device. Expects as argument an array [parameter_id, value, "
                    "num_bytes] where the final argument (num_bytes) may be "
                    "omitted and defaults to 1."),
                self._client.register(
                    self._remove_failed_node_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Send this event to instruct the ZWave controller to remove "
                    "this node. Only use on nodes whose 'is_failed' property is "
                    "true."),
                self.on_node_changed(),
                self._client.watch_event(self._heal_path,
                                         self._on_heal),
                self._client.watch_event(self._set_config_param_path,
                                         self._on_set_config_param),
                self._client.watch_event(self._remove_failed_node_path,
                                         self._on_remove_failed_node),
            ], loop=self._loop)
        finally:
            self._is_initialised.set()
    
    async def remove(self):
        """
        Unregister this node from Qth.
        """
        await self._is_initialised.wait()
        await asyncio.wait([
            self._client.unregister(self._is_failed_path),
            self._client.unregister(self._manufacturer_id_path),
            self._client.unregister(self._manufacturer_name_path),
            self._client.unregister(self._neighbours_path),
            self._client.unregister(self._product_id_path),
            self._client.unregister(self._product_name_path),
            self._client.unregister(self._product_type_path),
            self._client.unregister(self._heal_path),
            self._client.unregister(self._set_config_param_path),
            self._client.unregister(self._remove_failed_node_path),
            self._client.delete_property(self._is_failed_path),
            self._client.delete_property(self._manufacturer_id_path),
            self._client.delete_property(self._manufacturer_name_path),
            self._client.delete_property(self._neighbours_path),
            self._client.delete_property(self._product_id_path),
            self._client.delete_property(self._product_name_path),
            self._client.delete_property(self._product_type_path),
            self._client.unwatch_event(self._heal_path,
                                       self._on_heal),
            self._client.unwatch_event(self._set_config_param_path,
                                       self._on_set_config_param),
            self._client.unwatch_event(self._remove_failed_node_path,
                                       self._on_remove_failed_node),
        ] + [
            value.remove() for value in self._values.values()
        ], loop=self._loop)
    
    def _on_heal(self, _topic, _arg):
        self._ozw_node.heal()
    
    def _on_set_config_param(self, _topic, arg):
        assert isinstance(arg, list), "Argument should be list."
        assert len(arg) in [2, 3], "Argument must have two or three values."
        self._ozw_node.set_config_param(*arg)
    
    def _on_remove_failed_node(self, _topic, _arg):
        assert this._ozw_node.is_failed
        self._ozw_network.controller.remove_failed_node(this._ozw_node.node_id)
    
    async def on_node_changed(self):
        """
        Call when the node has changed for some reason.
        """
        await asyncio.wait([
            self._client.set_property(self._is_failed_path,
                                      self._ozw_node.is_failed),
            self._client.set_property(self._manufacturer_id_path,
                                      self._ozw_node.manufacturer_id),
            self._client.set_property(self._manufacturer_name_path,
                                      self._ozw_node.manufacturer_name),
            self._client.set_property(self._neighbours_path,
                                      list(self._ozw_node.neighbors)),
            self._client.set_property(self._product_id_path,
                                      self._ozw_node.product_id),
            self._client.set_property(self._product_name_path,
                                      self._ozw_node.product_name),
            self._client.set_property(self._product_type_path,
                                      self._ozw_node.product_type),
        ], loop=self._loop)
    
    async def on_value_changed(self, changed_ozw_value):
        """
        Call when a value is added or deleted or when that value has changed.
        """
        new_ozw_values = set(self._ozw_node.values.values())
        registered_ozw_values = set(self._values.keys())
        
        added = new_ozw_values - registered_ozw_values
        removed = registered_ozw_values - new_ozw_values
        
        todo = []
        
        # Add new values
        for ozw_value in added:
            value = Value(
                self._client,
                self._loop,
                self._ozw_network,
                ozw_value,
                self._qth_base_path,
                self._used_value_labels)
            self._values[ozw_value] = value
            todo.append(value.init_async())
        
        # Remove now absent values
        for ozw_value in removed:
            value = self._values.pop(ozw_value)
            todo.append(value.remove())
        
        if changed_ozw_value not in removed:
            todo.append(
                self._values[changed_ozw_value].on_zwave_value_changed())
        
        if todo:
            await asyncio.wait(todo, loop=self._loop)

class Network(object):
    """
    Logic for keeping a ZWave network object in sync with its Qth interface.
    """
    
    def __init__(self, client, loop, ozw_network, qth_base_path):
        self._client = client
        self._loop = loop
        self._ozw_network = ozw_network
        self._qth_base_path = qth_base_path
        
        self._ready_path = self._qth_base_path + "ready"
        self._state_path = self._qth_base_path + "state"
        self._home_id_path = self._qth_base_path + "home_id"
        self._heal_path = self._qth_base_path + "heal_network"
        self._add_node_path = self._qth_base_path + "add_node"
        self._remove_node_path = self._qth_base_path + "remove_node"
        
        self._last_is_ready = None
        self._last_state = None
        self._last_home_id = None
        
        self._is_initialised = asyncio.Event(loop=self._loop)
        
        # {owz.ZWaveNode: Node, ...}
        self._nodes = {}
    
    async def init_async(self):
        """
        Complete registration of the network. Must be called after
        instantiation.
        """
        try:
            await asyncio.wait([
                self._client.register(
                    self._ready_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "Boolean. True if the ZWave network is fully initialised.",
                    delete_on_unregister=True),
                self._client.register(
                    self._state_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "String. State of the OpenZWave client.",
                    delete_on_unregister=True),
                self._client.register(
                    self._home_id_path,
                    qth.PROPERTY_ONE_TO_MANY,
                    "Integer. The ZWave Home ID of the network.",
                    delete_on_unregister=True),
                self._client.register(
                    self._heal_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Trigger the network healing process."),
                self._client.register(
                    self._add_node_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Set the controller to node-adding mode."),
                self._client.register(
                    self._remove_node_path,
                    qth.EVENT_MANY_TO_ONE,
                    "Set the controller to node-removing mode."),
                self._client.watch_event(self._heal_path, self.on_heal),
                self._client.watch_event(self._add_node_path, self.on_add_node),
                self._client.watch_event(self._remove_node_path, self.on_remove_node),
                self.on_network_state_change(),
            ], loop=self._loop)
        finally:
            self._is_initialised.set()
    
    async def remove(self):
        """
        Unregister the network from Qth.
        """
        await self._is_initialised.wait()
        await asyncio.wait([
            self._client.unregister(self._ready_path),
            self._client.unregister(self._state_path),
            self._client.unregister(self._home_id_path),
            self._client.unregister(self._heal_path),
            self._client.unregister(self._add_node_path),
            self._client.unregister(self._remove_node_path),
            self._client.delete_property(self._ready_path),
            self._client.delete_property(self._state_path),
            self._client.delete_property(self._home_id_path),
            self._client.unwatch_event(self._heal_path, self.on_heal),
        ] + [
            node.remove() for node in self._nodes.values()
        ], loop=self._loop)
    
    async def on_network_state_change(self):
        """Call when the network state may have changed."""
        todo = []
        
        state = self._ozw_network.state_str
        if self._last_state != state:
            todo.append(self._client.set_property(self._state_path, state))
            self._last_state = state
        
        is_ready = self._ozw_network.state == self._ozw_network.STATE_READY
        if self._last_is_ready != is_ready:
            todo.append(self._client.set_property(self._ready_path, is_ready))
            self._last_is_ready = is_ready
            
            # When the network first becomes ready, also re-trigger the node
            # change event since OpenZWave does not provide an event when
            # certain data is loaded (e.g. Node neighbour list).
            if is_ready:
                for node in self._nodes.values():
                    todo.append(node.on_node_changed())
        
        home_id = self._ozw_network.home_id
        if self._last_home_id != home_id:
            todo.append(self._client.set_property(self._home_id_path, home_id))
            self._last_home_id = home_id
        
        if todo:
            await asyncio.wait(todo, loop=self._loop)
    
    async def on_nodes_changed(self, changed_ozw_node):
        """Call when the set of nodes may have changed."""
        new_ozw_nodes = set(self._ozw_network.nodes.values())
        registered_ozw_nodes = set(self._nodes.keys())
        
        added = new_ozw_nodes - registered_ozw_nodes
        removed = registered_ozw_nodes - new_ozw_nodes
        
        todo = []
        
        # Add new nodes
        for ozw_node in added:
            node = Node(
                self._client,
                self._loop,
                self._ozw_network,
                ozw_node,
                self._qth_base_path)
            self._nodes[ozw_node] = node
            todo.append(node.init_async())
        
        # Remove now absent nodes
        for ozw_node in removed:
            node = self._nodes.pop(ozw_node)
            todo.append(node.remove())
        
        if changed_ozw_node not in removed:
            todo.append(self._nodes[changed_ozw_node].on_node_changed())
        
        if todo:
            await asyncio.wait(todo, loop=self._loop)
    
    async def on_value_changed(self, ozw_node, ozw_value):
        """Call when the value of a node may have changed."""
        if ozw_node in self._nodes:
            await self._nodes[ozw_node].on_value_changed(ozw_value)
    
    async def on_heal(self, _path, _value):
        """Called when the 'heal_network' event is fired."""
        self._ozw_network.heal(True)
    
    async def on_add_node(self, _path, _value):
        """Called when the 'add_node' event is fired."""
        self._ozw_network.controller.add_node()
    
    async def on_remove_node(self, _path, value):
        """Called when the 'remove_node' event is fired."""
        self._ozw_network.controller.remove_node()


class QthZwave(object):
    
    def __init__(self, zwave_config_path, zwave_user_path,
                 zwave_device="/dev/ttyACM0",
                 qth_base_path="sys/zwave/",
                 host=None, port=None, keepalive=10, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        self._qth_base_path = qth_base_path
        
        self._client = qth.Client("qth_zwave",
                                  "Exposes Z-wave devices via Qth.",
                                  loop=self._loop, host=host, port=port,
                                  keepalive=keepalive)
        
        # Setup the OpenZWave client
        self._init_openzwave(zwave_device, zwave_config_path, zwave_user_path)
        
        # Setup the Qth mirror of the ZWave state
        self._network = Network(self._client,
                                self._loop,
                                self._ozw_network,
                                self._qth_base_path)
        self._loop.create_task(self._network.init_async())
        
        self._init_zwave_callbacks()
        
        self._ozw_network.start()
    
    def _init_openzwave(self, zwave_device, zwave_config_path, zwave_user_path):
        """Initialise the OpenZWave client, leaving it ready to start."""
        # Configure OpenZWave
        options = ZWaveOption(zwave_device,
                              config_path=zwave_config_path,
                              user_path=zwave_user_path,
                              cmd_line="")
        options.set_log_file(os.path.join(zwave_user_path, "zwave.log"))
        options.set_append_log_file(True)
        options.set_console_output(True)
        options.set_save_log_level("Warning")
        options.set_logging(True)
        options.lock()
        
        self._ozw_network = ZWaveNetwork(options, autostart=False)
    
    def _init_zwave_callbacks(self):
        """Setup callbacks for key OpenZWave events."""
        
        def threadsafe_wrap(f):
            def wrapper(*args, **kwargs):
                self._loop.call_soon_threadsafe(functools.partial(f, *args, **kwargs))
            return wrapper
        
        for state in [ZWaveNetwork.SIGNAL_NETWORK_FAILED,
                      ZWaveNetwork.SIGNAL_NETWORK_STARTED,
                      ZWaveNetwork.SIGNAL_NETWORK_READY,
                      ZWaveNetwork.SIGNAL_NETWORK_STOPPED,
                      ZWaveNetwork.SIGNAL_NETWORK_RESETTED,
                      ZWaveNetwork.SIGNAL_NETWORK_AWAKED]:
            dispatcher.connect(
                threadsafe_wrap(lambda *_, **__:
                    self._loop.create_task(
                        self._network.on_network_state_change())),
                state, weak=False)
        
        for signal in [ZWaveNetwork.SIGNAL_NODE_ADDED,
                       ZWaveNetwork.SIGNAL_NODE_REMOVED,
                       ZWaveNetwork.SIGNAL_NODE_EVENT]:
            dispatcher.connect(
                threadsafe_wrap(lambda node, *_, **__:
                    self._loop.create_task(
                        self._network.on_nodes_changed(node))),
                signal, weak=False)
        
        for signal in [ZWaveNetwork.SIGNAL_VALUE_ADDED,
                       ZWaveNetwork.SIGNAL_VALUE_REMOVED,
                       ZWaveNetwork.SIGNAL_VALUE_REFRESHED,
                       ZWaveNetwork.SIGNAL_VALUE_CHANGED]:
            dispatcher.connect(
                threadsafe_wrap(lambda node, value, *_, **__:
                    self._loop.create_task(
                        self._network.on_value_changed(node, value))),
                signal, weak=False)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="A Qth bridge for ZWave")
    
    parser.add_argument("--openzwave-config", "-z",
                        default="open-zwave/config",
                        help="Path of OpenZWave 'config' directory defining "
                             "options for all available ZWave devices.")
    parser.add_argument("--user-path", "-u", default="zwave",
                        help="Path of directory to store OpenZWave persistant "
                             "data.")
    parser.add_argument("--device", "-d", default="/dev/ttyACM0",
                        help="Path of ZWave controller serial port.")
    parser.add_argument("--qth-base", "-q", default="sys/zwave/",
                        help="Prefix for all Qth values.")
    
    parser.add_argument("--host", "-H", default=None,
                        help="Qth (MQTT) server hostname.")
    parser.add_argument("--port", "-P", default=None, type=int,
                        help="Qth (MQTT) server port number.")
    parser.add_argument("--keepalive", "-K", default=10, type=int,
                        help="MQTT keepalive interval (seconds).")
    parser.add_argument("--version", "-V", action="version",
                        version="$(prog)s {}".format(__version__))
    
    args = parser.parse_args()
    
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    
    qth_zwave = QthZwave(zwave_config_path=args.openzwave_config,
                         zwave_user_path=args.user_path,
                         zwave_device=args.device,
                         qth_base_path=args.qth_base,
                         host=args.host,
                         port=args.port,
                         keepalive=args.keepalive,
                         loop=loop)
    loop.run_forever()


if __name__ == "__main__":
    main()
