"""
This is essentially the bot.py from
https://github.com/jaraco/irc, with a couple of tweaks
"""

import sys
import warnings
import itertools
import random
import logging as log

import more_itertools

import irc.client
import irc.modes
from irc.dict import IRCDict
from irc.bot import ServerSpec, ReconnectStrategy, Channel

class ircBotException(Exception):
    pass

class ExponentialBackoff(ReconnectStrategy):
    """
    A ReconnectStrategy implementing exponential backoff
    with jitter.
    """

    min_interval = 3
    max_interval = 5

    def __init__(self, **attrs):
        vars(self).update(attrs)
        assert 0 <= self.min_interval <= self.max_interval
        self._check_scheduled = False
        self.attempt_count = itertools.count(1)

    def run(self, bot):
        if next(self.attempt_count) > 5:
            raise ircBotException("Failed to reconnect to server.")        
        self.bot = bot
        print("Disconnected from irc server, attempting to reconnect.")
        if self._check_scheduled:
            return
        # calculate interval in seconds based on connection attempts
        intvl = 2 ** next(self.attempt_count) - 1

        # limit the max interval
        intvl = min(intvl, self.max_interval)

        # add jitter and truncate to integer seconds
        intvl = int(intvl * random.random())

        # limit the min interval
        intvl = max(intvl, self.min_interval)

        self.bot.reactor.scheduler.execute_after(intvl, self.check)
        self._check_scheduled = True

    def check(self):
        self._check_scheduled = False
        if not self.bot.connection.is_connected():
            self.run(self.bot)
            self.bot.jump_server()

missing = object()


class SingleServerIRCBot(irc.client.SimpleIRCClient):
    """A single-server IRC bot class.

    The bot tries to reconnect if it is disconnected.

    The bot keeps track of the channels it has joined, the other
    clients that are present in the channels and which of those that
    have operator or voice modes.  The "database" is kept in the
    self.channels attribute, which is an IRCDict of Channels.

    Arguments:

        server_list -- A list of ServerSpec objects or tuples of
            parameters suitable for constructing ServerSpec
            objects. Defines the list of servers the bot will
            use (in order).

        nickname -- The bot's nickname.

        realname -- The bot's realname.

        recon -- A ReconnectStrategy for reconnecting on
            disconnect or failed connection.

        dcc_connections -- A list of initiated/accepted DCC
            connections.

        \*\*connect_params -- parameters to pass through to the connect
            method.
    """

    def __init__(
        self,
        server_list,
        nickname,
        realname,
        reconnection_interval=missing,
        recon=ExponentialBackoff(),
        **connect_params,
    ):
        super().__init__()
        self.__connect_params = connect_params
        self.channels = IRCDict()
        specs = map(ServerSpec.ensure, server_list)
        self.servers = more_itertools.peekable(itertools.cycle(specs))
        self.recon = recon
        # for compatibility
        if reconnection_interval is not missing:
            warnings.warn(
                "reconnection_interval is deprecated; "
                "pass a ReconnectStrategy object instead"
            )
            self.recon = ExponentialBackoff(min_interval=reconnection_interval)

        self._nickname = nickname
        self._realname = realname
        for i in [
            "disconnect",
            "join",
            "kick",
            "mode",
            "namreply",
            "nick",
            "part",
            "quit",
        ]:
            self.connection.add_global_handler(i, getattr(self, "_on_" + i), -20)

    def _connect(self):
        """
        Establish a connection to the server at the front of the server_list.
        """
        server = self.servers.peek()
        try:
            self.connect(
                server.host,
                server.port,
                self._nickname,
                server.password,
                ircname=self._realname,
                **self.__connect_params,
            )
        except irc.client.ServerConnectionError:
            self.connection._handle_event(irc.client.Event("disconnect", self.connection.server, "", [""]))

    def _on_disconnect(self, connection, event):
        self.channels = IRCDict()
        self.recon.run(self)

    def _on_join(self, connection, event):
        ch = event.target
        nick = event.source.nick
        if nick == connection.get_nickname():
            self.channels[ch] = Channel()
        self.channels[ch].add_user(nick)

    def _on_kick(self, connection, event):
        nick = event.arguments[0]
        channel = event.target

        if nick == connection.get_nickname():
            del self.channels[channel]
        else:
            self.channels[channel].remove_user(nick)

    def _on_mode(self, connection, event):
        t = event.target
        if not irc.client.is_channel(t):
            # mode on self; disregard
            return
        ch = self.channels[t]

        modes = irc.modes.parse_channel_modes(" ".join(event.arguments))
        for sign, mode, argument in modes:
            f = {"+": ch.set_mode, "-": ch.clear_mode}[sign]
            f(mode, argument)

    def _on_namreply(self, connection, event):
        """
        event.arguments[0] == "@" for secret channels,
                          "*" for private channels,
                          "=" for others (public channels)
        event.arguments[1] == channel
        event.arguments[2] == nick list
        """

        ch_type, channel, nick_list = event.arguments

        if channel == '*':
            # User is not in any visible channel
            # http://tools.ietf.org/html/rfc2812#section-3.2.5
            return

        for nick in nick_list.split():
            nick_modes = []

            if nick[0] in self.connection.features.prefix:
                nick_modes.append(self.connection.features.prefix[nick[0]])
                nick = nick[1:]

            for mode in nick_modes:
                self.channels[channel].set_mode(mode, nick)

            self.channels[channel].add_user(nick)

    def _on_nick(self, connection, event):
        before = event.source.nick
        after = event.target
        for ch in self.channels.values():
            if ch.has_user(before):
                ch.change_nick(before, after)

    def _on_part(self, connection, event):
        nick = event.source.nick
        channel = event.target

        if nick == connection.get_nickname():
            del self.channels[channel]
        else:
            self.channels[channel].remove_user(nick)

    def _on_quit(self, connection, event):
        nick = event.source.nick
        for ch in self.channels.values():
            if ch.has_user(nick):
                ch.remove_user(nick)

    def die(self, msg="Bye, cruel world!"):
        """Let the bot die.

        Arguments:

            msg -- Quit message.
        """

        self.connection.disconnect(msg)
        sys.exit(0)

    def disconnect(self, msg="I'll be back!"):
        """Disconnect the bot.

        The bot will try to reconnect after a while.

        Arguments:

            msg -- Quit message.
        """
        self.connection.disconnect(msg)

    @staticmethod
    def get_version():
        """Returns the bot version.

        Used when answering a CTCP VERSION request.
        """
        return f"Python irc.bot ({irc._get_version()})"

    def jump_server(self, msg="Changing servers"):
        """Connect to a new server, possibly disconnecting from the current.

        The bot will skip to next server in the server_list each time
        jump_server is called.
        """
        if self.connection.is_connected():
            self.connection.disconnect(msg)

        next(self.servers)
        self._connect()

    def on_ctcp(self, connection, event):
        """Default handler for ctcp events.

        Replies to VERSION and PING requests and relays DCC requests
        to the on_dccchat method.
        """
        nick = event.source.nick
        if event.arguments[0] == "VERSION":
            connection.ctcp_reply(nick, "VERSION " + self.get_version())
        elif event.arguments[0] == "PING":
            if len(event.arguments) > 1:
                connection.ctcp_reply(nick, "PING " + event.arguments[1])
        elif (
            event.arguments[0] == "DCC"
            and event.arguments[1].split(" ", 1)[0] == "CHAT"
        ):
            self.on_dccchat(connection, event)

    def on_dccchat(self, connection, event):
        pass

    def start(self):
        """Start the bot."""
        self._connect()
        super().start()

class BridgeIrcBot(SingleServerIRCBot):
    def __init__(self, instance, imq, urbit_client, channels, nickname, server, port=6667, password=""):
        self.instance = instance
        self.channel_list = channels
        self.message_queue = imq
        self.urbit_client = urbit_client
        SingleServerIRCBot.__init__(self, [(server, port, password)], nickname, nickname)
        self.reactor.scheduler.execute_every(0.1, self.check_queue)

    def on_nicknameinuse(self, c, e):
        log.error("Nickname is in use")
        raise ircBotException("Nickname in use")

    def on_welcome(self, c, e):
        if len(self.channel_list) < 1:
            raise ircBotException("No channels passed")
        
        for channel in self.channel_list:
            c.join(channel)

    def on_pubmsg(self, c, e):
        urbit_channels = list(filter(
            lambda chan: chan["irc_channel"] == e.target,
            self.instance["channels"]
        ))
        if len(urbit_channels) > 0:
            for urbit_channel in urbit_channels:
                self.urbit_client.send_message(
                    urbit_channel["resource_ship"],
                    urbit_channel["urbit_channel"],
                    "%s: %s" % (e.source.split("!")[0], e.arguments[0])
                )

    def check_queue(self):
            if self.message_queue.empty():
                return
            data = self.message_queue.get()
            self.connection.privmsg(data[0], data[1])