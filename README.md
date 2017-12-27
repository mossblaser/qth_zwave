Qth ZWave
=========

Qth ZWave exposes [ZWave](http://www.z-wave.com/) home automation devices via
[Qth](https://github.com/mossblaser/qth).

Qth ZWave is built on
[OpenZWave](http://www.openzwave.net/)/[Python-OpenZWave](https://github.com/OpenZWave/python-openzwave)
and exposes a minimal subset of the functionality available via OpenZWave. This
includes listing of ZWave nodes and values, fetching and setting those values
and accessing metadata related to those values. The intention is that more
advanced functionality be implemented via other Qth clients.

Setup
-----

Qth ZWave requires a copy of the OpenZWave configuration database which
includes descriptions of most commercially available ZWave modules. You can get
the latest version from GitHub like so:

    $ git clone https://github.com/OpenZWave/open-zwave

The configuration database will now be located in `open-zwave/config/`. Make a
note of this directory.

You also need to create a directory for OpenZWave to write its log files and
store a cache of ZWave node information.

    $ mkdir zwave

Make a note of this directory too.

Now you can start the Qth ZWave server like so:

    $ qth_zwave


Qth API
-------

By default Qth ZWave will create events and properties under the path
`sys/zwave/` in the Qth tree. Usage information is provided in the Qth
registration description but a summary is given below:

* `sys/zwave/`
  * `ready`: 1:N Property. Is the network ready yet.
  * `state`: 1:N Property. OpenZWave library state.
  * `home_id`: 1:N Property. The ZWave Home ID.
  * `<NODE ID HERE>/`
    * `is_failed`: 1:N Property. Has this node failed?
    * `manufacturer_id`: 1:N Property. ZWave manufacturer ID.
    * `manufacturer_name`: 1:N Property. Manufacturer name.
    * `neighbours`: 1:N Property. Node IDs visible from this node.
    * `product_id`: 1:N Property. ZWave product ID.
    * `product_name`: 1:N Property. Product name.
    * `product_type`: 1:N Property. ZWave product type code.
    * `heal`: N:1 Event. Send this event to send the 'heal' command to this
      node.
    * `set_config_param`: N:1 Event. Set a ZWave configuration parameter.
    * `remove_failed_node`: N:1 Event. Remove this node if it has failed.
    * `values/`
      * `<VALUE LABEL HERE>`: N:1 Property. The data held by this value.
        Setting this property writes the value on the ZWave device. When the
        ZWave device changes the value, this property will also be set.
      * `<VALUE LABEL HERE>/units`: 1:N Property. The unit type reported by
        ZWave.
      * `<VALUE LABEL HERE>/refresh`: N:1 Event. Send a refresh command to
        ZWave.
