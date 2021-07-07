"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Perhaps a rimmed-down version of explorations/test_find_first_and_load.py
"""

DISCONNECT_AT_END = True

import asyncio
import json
import logging
import os
import queue
import time

from socket import gethostname
from typing import Optional, NamedTuple

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage, MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

import requests

from pyDE1.dispatcher.resource import Resource, DE1ModeEnum, ConnectivityEnum

logger = logging.getLogger('main')
logger_scanner = logging.getLogger('Scanner')
logger_connect = logging.getLogger('Connect')

logging.getLogger('asyncio').setLevel(logging.INFO)

format_string = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=logging.DEBUG,
                    format=format_string,
                    )

MQTT_TOPIC_ROOT = 'pyDE1'

MQTT_CLIENT_ID = f"ui@{gethostname()}[{os.getpid()}]"

MQTT_BROKER_HOSTNAME = '::'
MQTT_BROKER_PORT = 1883

MQTT_TRANSPORT = 'tcp'
MQTT_TLS_CONTEXT = None
MQTT_KEEPALIVE = 60

MQTT_USERNAME = None
MQTT_PASSWORD = None

SERVER_HOST = 'localhost'
SERVER_PORT = 1234
SERVER_ROOT = '/'


def path_of(res: Resource):
    return f"http://{SERVER_HOST}:{SERVER_PORT}" \
           f"{os.path.join(SERVER_ROOT, res.value)}"


async def run():

    def show_result(r: requests.Response):
        body = r.request.body
        if isinstance(body, (bytes, bytearray)):
            body = body.decode('utf-8')
        logger.debug(f"{r.status_code} {r.request.method} {r.request.url}\n"
              f"{body}\n{r.text}")

    have_de1 = asyncio.Event()
    have_scale = asyncio.Event()

    def is_connected(res: Resource):
        r = requests.get(path_of(res))
        show_result(r)
        retval = None
        try:
            retval = r.json()['mode'] == ConnectivityEnum.CONNECTED.value
        finally:
            return retval

    if is_connected(Resource.DE1_CONNECTIVITY):
        have_de1.set()

    if is_connected(Resource.SCALE_CONNECTIVITY):
        have_scale.set()

    def find_first(res: Resource):
        t0 = time.time()
        r = requests.patch(path_of(res),
                           json = {"first_if_found": True})
        t1 = time.time()
        show_result(r)
        logger.debug(f"{res} elapsed time: {(t1 - t0):.3f} seconds")

    def connect(res: Resource, id: Optional[str]):
        t0 = time.time()
        r = requests.patch(path_of(res),
                           json = {"id": id})
        t1 = time.time()
        show_result(r)
        logger.debug(f"{res} elapsed time: {(t1 - t0):.3f} seconds")

    def upload_profile(filename: str):
        logger.debug(f"cwd: {os.path.abspath(os.curdir)}")
        with open(filename, 'rb') as profile:
            logger.debug(f"opened: {filename}")
            r = requests.put(path_of(Resource.DE1_PROFILE),
                             data = profile)
        show_result(r)

    def set_saw(mass: float):
        r = requests.patch(path_of(Resource.DE1_CONTROL_ESPRESSO),
                           json={"stop_at_time": None,
                                 "stop_at_volume": None,
                                 "stop_at_weight": 50})
        show_result(r)

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        logger.debug(f"CB: Connect: flags: {flags}, reasonCode: {reasonCode}, "
              f"properties {properties}")

    topic_scanner = f"{MQTT_TOPIC_ROOT}/ScannerNotification"
    topic_connect = f"{MQTT_TOPIC_ROOT}/ConnectivityChange"

    def scan_message_cb(client: mqtt.Client, userdata, message: MQTTMessage):
        payload_dict = json.loads(message.payload)
        # logger.debug(payload_dict)
        if message.topic == topic_scanner:
            id = payload_dict['id']
            name = payload_dict['name']
            action = payload_dict['action']
            logger_scanner.debug(f"{action}: {name} {id}")
        elif message.topic == topic_connect:
            logger_connect.debug(
                f"{payload_dict['sender']}: {payload_dict['state']}")
        else:
            pass

    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        clean_session=None,  # Required for MQTT5
        userdata=None,
        protocol=MQTTv5,
        transport=MQTT_TRANSPORT,
    )

    mqtt_client.on_connect = on_connect_callback
    mqtt_client.on_message = scan_message_cb

    mqtt_client.connect(host=MQTT_BROKER_HOSTNAME,
                   port=MQTT_BROKER_PORT,
                   keepalive=MQTT_KEEPALIVE,
                   bind_address="",
                   bind_port=0,
                   clean_start=MQTT_CLEAN_START_FIRST_ONLY,
                   properties=None)

    mqtt_client.subscribe(topic_scanner)
    mqtt_client.subscribe(topic_connect)
    mqtt_client.loop_start()

    # Wait a second for the loop to start (ugly)
    await asyncio.sleep(1)

    t0 = time.time()

    find_first(Resource.DE1_ID)
    find_first(Resource.SCALE_ID)

    t1 = time.time()
    logger.debug(f"##### Connection time: {(t1 - t0):.3f} seconds")

    # TODO: How to manage "ready" event if the DE1 or scale
    #       was already connected and ready when this started?

    # TODO: This should wait for DE1 ready
    upload_profile('/home/ble-remote/devel/pyDE1/examples/jmk_eb6.json')
    set_saw(50.0)

    if DISCONNECT_AT_END:
        connect(Resource.SCALE_ID, None)
        connect(Resource.DE1_ID, None)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    logger.info("Done")

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(run())
