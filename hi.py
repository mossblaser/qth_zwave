import sys
import time

from pydispatch import dispatcher

from openzwave.option import ZWaveOption
from openzwave.network import ZWaveNetwork

#import openzwave
#from openzwave.node import ZWaveNode
#from openzwave.value import ZWaveValue
#from openzwave.scene import ZWaveScene
#from openzwave.controller import ZWaveController

device = "/dev/ttyACM0"
sniff = 300.0

options = ZWaveOption(device,
                      config_path="./ozw/config",
                      user_path="./zwave/",
                      cmd_line="")
options.set_log_file("./zwave/OZW_Log.log")
options.set_append_log_file(True)
options.set_console_output(True)
options.set_save_log_level("Warning")
#options.set_save_log_level("Debug")
options.set_logging(True)
options.lock()

network = ZWaveNetwork(options, autostart=False)

def make_printer(prefix):
  def f(*a, **kw):
    try:
      things = []
      if "network" in kw:
        kw.pop("network")
      if "signal" in kw:
        assert kw.pop("signal") == prefix
      if "node" in kw:
        things.append("Node:{}".format(kw.pop("node").node_id))
      if "value" in kw:
        value = kw.pop("value")
        things.append("Value {!r}: {!r}".format(value.label, value.data))
      print(prefix, a, kw, *things)
    except Exception as e:
      print(repr(e))
  return f

import functools
cbs = {}
for signal in [
  network.SIGNAL_NETWORK_READY,
  network.SIGNAL_ALL_NODES_QUERIED,
  network.SIGNAL_NODE_ADDED,
  network.SIGNAL_NODE_EVENT,
  network.SIGNAL_NODE_READY,
  network.SIGNAL_NODE_REMOVED,
  network.SIGNAL_VALUE_CHANGED,
  network.SIGNAL_VALUE_ADDED,
  network.SIGNAL_VALUE_REFRESHED,
  network.SIGNAL_VALUE_REMOVED,
]:
  cbs[signal] = make_printer(signal)
  dispatcher.connect(cbs[signal], signal, weak=False)

network.start()

for _ in range(120):
  if network.state != network.STATE_READY:
    print("Waiting for network to be ready...")
    time.sleep(1)
  else:
    break
else:
  print("Timeout waiting for network ready")
  network.stop()
  sys.exit(1)

print("Network ready...")
time.sleep(5)

for node_id, node in network.nodes.items():
  print("Got node: {}".format(node_id))
  if not node.is_ready:
    print("  Node is dead...")
  elif "Flush Dimmer" in node.product_name:
    print("  Flush dimmer, setting switch mode")
    # Set switches to toggle mode
    node.set_config_param(1, 1)
    node.set_config_param(2, 1)
    
    # Enable two/three-way switch
    node.set_config_param(20, 1, 1) #  Enable
    
    # Enable fast double click = max brightness
    node.set_config_param(21, 1, 1) #  Enable
    
    # Set dimming time when button pressed
    node.set_config_param(65, 50) #  500 ms
    
    # Set time when change command sent
    node.set_config_param(65, 50) #  500 ms (the minimum)
    node.set_config_param(68, 1, 1) #  1 second (the minimum)
  else:
    print("  Not a flush dimmer...")

try:
  while True:
    brightness = int(input("Brightness > "))
    for node_id, node in network.nodes.items():
      if node.is_ready:
        for value_id, value in node.values.items():
          if value.label == "Level":
            node.set_dimmer(value_id, brightness)
finally:
  network.stop()
