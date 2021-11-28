import os
import threading
import logging
import re
import json

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

import paho.mqtt.client as mqtt

def render_key_image(deck_sn, deck, icon_text, label_text):
    global icon_fonts_by_sn
    global label_font
    image = PILHelper.create_image(deck)

    draw = ImageDraw.Draw(image)

    if icon_text:
        icon_font = icon_fonts_by_sn[deck_sn]
        v = (image.height - 20) if label_text else image.height
        draw.text((image.width / 2, v / 2), text=icon_text, font=icon_font, anchor="mm", fill="white")

    if label_text:
        v = (image.height - 5) if icon_text else (image.height / 2)
        draw.text((image.width / 2, v), text=label_text, font=label_font, anchor="ms", fill="white")

    return PILHelper.to_native_format(deck, image)

def on_connect(client, userdata, flags, rc):
    global client_id
    global streamdecks
    global serial_numbers

    print("MQTT: Connected with result code "+str(rc))

    client.subscribe("streamdeck/#")

    client.publish(f'streamdeck/{client_id}/availability', 'online', retain=True)

    for index, deck in enumerate(streamdecks):
        deck_sn = serial_numbers[deck.id()]
        for key_id in range(deck.key_count()):
            config = json.dumps({
                "unique_id": f"streamdeck_{deck_sn}_{key_id}",
                "name": f"StreamDeck Key {key_id}", 
                "state_topic": f"streamdeck/{deck_sn}/{key_id}/state",
                "availability_topic": f"streamdeck/{client_id}/availability",
                "json_attributes_topic": f"streamdeck/{deck_sn}/{key_id}/attributes",
                "icon": "mdi:keyboard",
                "device": {
                    "identifiers": [deck_sn],
                    "name": "StreamDeck"
                }
            })
            client.publish(f'homeassistant/binary_sensor/streamdeck_{deck_sn}_{key_id}/config', config, retain=True)
            client.publish(f"streamdeck/{deck_sn}/{key_id}/attributes", json.dumps({
                "number": key_id
            }), retain=True)
            

def on_message(client, userdata, msg):
    global streamdecks_by_sn
    global keys

    print(f'MQTT: {msg.topic} = {str(msg.payload)}')

    p = re.compile(r'streamdeck/([^/]+)/(\d+)/(text|icon|set)')
    m = p.match(msg.topic)
    if m:
        deck_sn = m.group(1)
        key_id = int(m.group(2))
        prop = m.group(3)
        value = msg.payload.decode('utf-8')
        print(f'RE: Deck="{deck_sn}" Key="{key_id}" Prop="{prop}" = "{value}"')

        deck = streamdecks_by_sn[deck_sn]
        key = keys.setdefault(key_id, {})

        if prop == 'set':
            keys[key_id] = key = json.loads(value)
        else:
            key[prop] = value

        image = render_key_image(deck_sn, deck, key.get('icon'), key.get('text'))
        with deck:
            deck.set_key_image(key_id, image)

def on_key_change(deck, key, state):
    global client
    global serial_numbers
    print(f'StreamDeck: Deck {serial_numbers[deck.id()]} Key {key} = {state}', flush=True)

    client.publish(f'streamdeck/{serial_numbers[deck.id()]}/{key}/state', 'ON' if state else 'OFF', retain=True)

with open("config.json") as json_data_file:
    config = json.load(json_data_file)
print(config)

if config.get('debug'):
    logging.basicConfig(level=logging.DEBUG)

label_font = ImageFont.truetype('Roboto-Regular.ttf', 14)

streamdecks = DeviceManager().enumerate()
serial_numbers = {}
streamdecks_by_sn = {}
icon_fonts_by_sn = {}
keys = {}

print(f'Found {len(streamdecks)} Stream Deck(s)')

for index, deck in enumerate(streamdecks):
    deck.open()
    deck.reset()

    deck.set_brightness(30)
    deck.set_key_callback(on_key_change)

    sn = deck.get_serial_number().replace('\0', '').replace('\x01', '')
    serial_numbers[deck.id()] = sn
    streamdecks_by_sn[sn] = deck

    key_width, key_height = deck.key_image_format()['size']

    icon_fonts_by_sn[sn] = ImageFont.truetype('materialdesignicons-webfont.ttf', key_height)

client_id = "streamdeck2mqtt"
client = mqtt.Client(client_id=client_id, clean_session=False)
client.username_pw_set(config['mqtt_username'], config['mqtt_password'])
client.will_set(f'streamdeck/{client_id}/availability', 'offline')
client.on_connect = on_connect
client.on_message = on_message
client.enable_logger()

client.connect(config['mqtt_server'])
client.loop_forever()
