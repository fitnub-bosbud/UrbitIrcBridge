import asyncio
from multiprocessing import Process, Queue, active_children
from base_bridge import *
from helpers import getjson_dump
from irc_bot import BridgeIrcBot
import quinnat

class irc_message_putter:
    def __init__(self, message_queue):
        self.message_queue = message_queue
    
    def send(self, data):
        self.message_queue.put(data)


class urbit_client:
    def __init__(self, instance):
        self.instance = instance
        self.connect()
    
    def connect(self):
        self.client = quinnat.Quinnat(
        self.instance["urbit_url"],
        self.instance["client_ship"],
        self.instance["urbit_code"]
    )
        self.client.connect()
    
    def send_message(self, resource_ship, channel, message):
        try:
            self.client.post_message(
                resource_ship,
                channel,
                {"text": message}
            )
        except UnicodeDecodeError:
            self.reconnect()

    def reconnect(self):
         self.client.ship.delete()
         self.client = self.connect()

class urbit_bot():

    def __init__(self, instance, urb_info, sender):
        self.instance = instance
        self.urbit_client = urbit_client(urb_info)
        self.urb_info = urb_info
        self.sender = sender

    def start(self):
        async def urbit_message_handler(message, _):
            matched_ships = list(filter(lambda ship: ship["resource_ship"] == message.host_ship, self.instance["channels"]))
            if len(matched_ships) > 0:
                for matched_ship in matched_ships:
                    if matched_ship["urbit_channel"] == message.resource_name:
                        message_data = message.author + ": " + message.full_text
                        self.sender.send((matched_ship["irc_channel"], message_data))

        def urbit_listener(message, _):
            asyncio.run(urbit_message_handler(message, _))

        while True:
            try:
                self.urbit_client.client.listen(urbit_listener)
            except UnicodeDecodeError:
                self.urbit_client.reconnect()
                continue


class irc_bridge(generic_bridge):
    def __init__(self, instance, urb_info, mq):
        super().__init__(instance)
        self.urb_info = urb_info
        self.instance = instance
        self.mq = mq
        self.nickname = instance["irc_nickname"]
        self.hostname = instance["irc_hostname"]
        self.channel_list = []
        if "irc_password" in instance:
            self.password = instance["irc_password"]
        else:
            self.password = ""
        if "irc_port" in instance:
            self.port = instance["irc_port"]
        else:
            self.port = 6667
            
        for channel_group in instance["channels"]:
            self.channel_list.append(channel_group["irc_channel"])

    def start(self):
        bridge = BridgeIrcBot(self.instance, self.mq, urbit_client(self.urb_info), self.channel_list, self.nickname, self.hostname, self.port, self.password)
        bridge.start()

if __name__ == "__main__":
    procs = []
    for instance in getjson_dump("config.json"):
        urb_info = {
                        "urbit_url": instance["urbit_url"],   
                        "client_ship": instance["client_ship"],
                        "urbit_code": instance["urbit_code"]
                    }
        for bot in instance["bots"]:
            if bot["type"] == "irc":
                imq = Queue()
                sender = irc_message_putter(imq)
                urblistener_instance = urbit_bot(bot, urb_info, sender)
                bridge_instance = irc_bridge(bot, urb_info, imq)
            else:    
                raise Exception("type not implemented")

            bridge_proc = Process(target=bridge_instance.start)
            urblistener_proc = Process(target=urblistener_instance.start)
            
            bridge_proc.start()
            urblistener_proc.start()
            procs.append(bridge_proc)
            procs.append(urblistener_proc)
    
    for proc in procs:
        proc.join()
