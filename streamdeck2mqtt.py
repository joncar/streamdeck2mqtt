import os
import threading
import logging
import re
import json
import signal

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

import paho.mqtt.client as mqtt

class StreamDeck2MQTT:
    def render_key_image(self, icon_text, label_text):
        image = PILHelper.create_image(self.deck)

        draw = ImageDraw.Draw(image)

        if icon_text:
            v = (image.height - 20) if label_text else image.height
            draw.text((image.width / 2, v / 2), text=icon_text, font=self.icon_font, anchor="mm", fill="white")

        if label_text:
            v = (image.height - 5) if icon_text else (image.height / 2)
            draw.text((image.width / 2, v), text=label_text, font=self.label_font, anchor="ms", fill="white")

        return PILHelper.to_native_format(self.deck, image)

    def on_connect(self, client, userdata, flags, rc):
        self.client.subscribe(f"streamdeck/{self.deck_sn}/#")

        self.client.publish(f'streamdeck/{self.deck_sn}/availability', 'online', retain=True)

        for key_id in range(self.deck.key_count()):
            config = json.dumps({
                "unique_id": f"streamdeck_{self.deck_sn}_{key_id}",
                "name": f"StreamDeck Key {key_id}", 
                "state_topic": f"streamdeck/{self.deck_sn}/{key_id}/state",
                "availability_topic": f"streamdeck/{self.deck_sn}/availability",
                "json_attributes_topic": f"streamdeck/{self.deck_sn}/{key_id}/attributes",
                "icon": "mdi:keyboard",
                "device": {
                    "identifiers": [self.deck_sn],
                    "name": "StreamDeck"
                }
            })
            self.client.publish(f'homeassistant/binary_sensor/streamdeck_{self.deck_sn}_{key_id}/config', config, retain=True)
            self.client.publish(f"streamdeck/{self.deck_sn}/{key_id}/attributes", json.dumps({
                "number": key_id
            }), retain=True)
                

    def on_message(self, client, userdata, msg):
        p = re.compile(r'streamdeck/([^/]+)/(\d+)/(text|icon|set)')
        m = p.match(msg.topic)
        if m:
            deck_sn = m.group(1)
            key_id = int(m.group(2))
            prop = m.group(3)
            value = msg.payload.decode('utf-8')

            key = self.keys.setdefault(key_id, {})

            if prop == 'set':
                self.keys[key_id] = key = json.loads(value)
            else:
                key[prop] = value

            image = self.render_key_image(key.get('icon'), key.get('text'))
            with self.deck:
                self.deck.set_key_image(key_id, image)

    def on_key_change(self, deck, key, state):
        self.client.publish(f'streamdeck/{self.deck_sn}/{key}/state', 'ON' if state else 'OFF', retain=True)

    def __init__(self, deck):
        self.deck = deck
        self.keys = {}

    def start(self, config):
        self.deck.open()
        self.deck.reset()

        self.deck.set_brightness(30)
        self.deck.set_key_callback(self.on_key_change)

        self.deck_sn = self.deck.get_serial_number().replace('\0', '').replace('\x01', '')

        key_width, key_height = self.deck.key_image_format()['size']
        self.icon_font = ImageFont.truetype('materialdesignicons-webfont.ttf', key_height)

        self.label_font = ImageFont.truetype('Roboto-Regular.ttf', 14)

        client_id = f"streamdeck2mqtt_{self.deck_sn}"
        self.client = mqtt.Client(client_id=client_id, clean_session=False)
        self.client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
        self.client.will_set(f'streamdeck/{self.deck_sn}/availability', 'offline')
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        if config.get('debug'):
            self.client.enable_logger()

        self.client.connect(config['mqtt_server'])
        self.client.loop_start()

with open("config.json") as json_data_file:
    config = json.load(json_data_file)

if config.get('debug'):
    logging.basicConfig(level=logging.DEBUG)

for deck in DeviceManager().enumerate():
    worker = StreamDeck2MQTT(deck)
    worker.start(config)

signal.pause()