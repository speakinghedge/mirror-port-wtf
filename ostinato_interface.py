import sys
import time
import jsonpickle

from ostinato.core import ost_pb, DroneProxy
from ostinato.protocols.mac_pb2 import mac
from ostinato.protocols.ip4_pb2 import ip4, Ip4
from ostinato.protocols.protocol_pb2 import StreamCore


class TXPortConfig(object):
    def __init__(self, interface_name, is_mirrored_port, src_mac, dst_mac, frame_len, speed_mbit):
        self.interface_name = interface_name
        self.is_mirrored_port = is_mirrored_port
        self.src_mac = src_mac
        self.dst_mac = dst_mac
        self.frame_len = frame_len
        self.speed_mbit = speed_mbit

        self._duration = None
        self._frames_total_calculated = None
        self._frames_per_second_calculated = None
        self._stream = None

    @property
    def duration(self):
        if not self._duration:
            raise ValueError('value not set.')
        return self._duration

    @duration.setter
    def duration(self, value):
        if value < 0:
            raise ValueError('must be >= 0')
        self._duration = value

    @property
    def frames_total_calculated(self):
        if not self._frames_total_calculated:
            raise ValueError('value not set.')
        return self._frames_total_calculated

    @frames_total_calculated.setter
    def frames_total_calculated(self, value):
        if value < 0:
            raise ValueError('must be >= 0')
        self._frames_total_calculated = value

    @property
    def frames_per_second_calculated(self):
        if not self._frames_per_second_calculated:
            raise ValueError('value not set.')
        return self._frames_per_second_calculated

    @frames_per_second_calculated.setter
    def frames_per_second_calculated(self, value):
        if value < 0:
            raise ValueError('must be >= 0')
        self._frames_per_second_calculated = value

    @property
    def stream(self):
        if not self._stream:
            raise ValueError('value not set - stream not valid.')
        return self._stream

    @stream.setter
    def stream(self, value):
        self._stream = value


class RXTXStats:
    def __init__(self, interface_name, rx_bytes, rx_frames, tx_bytes, tx_frames, is_mirror_port=False,
                 is_mirrored_port=False, speed_mbit=0):
        self.interface_name = interface_name
        self.is_mirror_port = is_mirror_port
        self.is_mirrored_port = is_mirrored_port
        self.speed_mbit = speed_mbit
        self.rx_bytes = rx_bytes
        self.rx_frames = rx_frames
        self.tx_bytes = tx_bytes
        self.tx_frames = tx_frames

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return '{:<7}, is_mirror: {:<1}, is_mirrored: {:<1}, speed_mbit: {:<3}, rx_bytes: {:<8}, rx_frames: {:<8}, tx_bytes: {:<8}, tx_frames: {:<8}'.format(
            self.interface_name,
            self.is_mirror_port,
            self.is_mirrored_port,
            self.speed_mbit,
            self.rx_bytes,
            self.rx_frames,
            self.tx_bytes,
            self.tx_frames)


class OstinatoInterface(object):
    def __init__(self, host_name='127.0.0.1', rx_interface='eth0', accepted_tx_diff=1):

        self._tx_port_configs = []
        self._interface_statistics = []

        self._tx_port_ids = ost_pb.PortIdList()
        self._rx_port_ids = ost_pb.PortIdList()
        self._stream_id_cntr = 1

        self._drone = DroneProxy(host_name)
        self._drone.connect()

        self._port_id_list = self._drone.getPortIdList()
        self._port_configs = self._drone.getPortConfig(self._port_id_list)

        if rx_interface:
            self._rx_port_add(rx_interface)

        self._accepted_tx_diff = accepted_tx_diff

    def _rx_port_add(self, interface_name):
        """
        add given interface to rx port id list
        :param interface_name: name of the nic to be added
        :return: related port_id object
        """
        port_id = self._port_id_by_interface_name(interface_name)

        self._rx_port_ids.port_id.add().id = port_id.id

        return port_id

    def _tx_port_add(self, interface_name):
        """
        add given interface to tx port id list
        :param interface_name: name of the nic to be added
        :return: related port_id object
        """
        port_id = self._port_id_by_interface_name(interface_name)
        self._tx_port_ids.port_id.add().id = port_id.id

        return port_id

    def _interface_name_by_port_id(self, port_id):

        for port in self._port_configs.port:
            if port_id.id == port.port_id.id:
                return port.name

        raise ValueError('Unknown or invalid port id: {}'.format(port_id))

    def _port_id_by_interface_name(self, interface_name):

        for port in self._port_configs.port:
            if interface_name == port.name:
                return port.port_id

        raise ValueError('Unknown or invalid interface name: {}'.format(interface_name))

    def ports_available_list(self):

        for port in self._port_configs.port:
            print 'id: {:2} name: {:10}'.format(port.port_id.id, port.name)

    def tx_ports_dump(self):

        for port in self._tx_port_configs:
            print 'id: {:2} name: {:10} frame_len: {}  speed: {}'.format(port.port_id.id, port.interface_name,
                                                                         port.frame_len, port.speed_mbit)

    def tx_port_config_add(self, tx_port_config):

        assert (type(tx_port_config) == TXPortConfig)

        port_id = self._tx_port_add(tx_port_config.interface_name)
        tx_port_config.port_id = port_id

        self._tx_port_configs.append(tx_port_config)

    def _prepare_stream(self, tx_port_config, duration):

        stream_ids = ost_pb.StreamIdList()
        stream_ids.port_id.CopyFrom(tx_port_config.port_id)
        stream_ids.stream_id.add().id = self._stream_id_cntr
        self._stream_id_cntr += 1

        self._drone.addStream(stream_ids)

        port_stream_cfg = ost_pb.StreamConfigList()

        port_stream_cfg.port_id.CopyFrom(tx_port_config.port_id)

        stream = port_stream_cfg.stream.add()
        stream.stream_id.id = stream_ids.stream_id[0].id

        stream.core.is_enabled = True

        stream.core.len_mode = StreamCore.e_fl_fixed
        stream.core.frame_len = tx_port_config.frame_len

        tx_port_config.duration = duration

        if tx_port_config.speed_mbit:

            frames_per_sec, frames_total = self._mbit_len_to_frames_per_sec(tx_port_config.speed_mbit,
                                                                            tx_port_config.frame_len,
                                                                            duration)

            tx_port_config.frames_total_calculated = frames_total
            tx_port_config.frames_per_second_calculated = frames_per_sec
            stream.control.num_packets = frames_total
            stream.control.packets_per_sec = frames_per_sec

        else:
            tx_port_config.frames_total_calculated = 1
            tx_port_config.frames_per_second_calculated = 1
            stream.control.num_packets = 1
            stream.control.packets_per_sec = 1
            # stream.control.bursts_per_sec = 10

        p = stream.protocol.add()
        p.protocol_id.id = ost_pb.Protocol.kMacFieldNumber

        p.Extensions[mac].src_mac = tx_port_config.src_mac
        p.Extensions[mac].dst_mac = tx_port_config.dst_mac

        p = stream.protocol.add()
        p.protocol_id.id = ost_pb.Protocol.kEth2FieldNumber

        p = stream.protocol.add()
        p.protocol_id.id = ost_pb.Protocol.kIp4FieldNumber

        ip = p.Extensions[ip4]
        ip.src_ip = 0x00000000
        ip.dst_ip = 0x00000000
        # ip.dst_ip_mode = Ip4.e_im_inc_host
        ip.dst_ip_mode = Ip4.e_im_fixed

        stream.protocol.add().protocol_id.id = ost_pb.Protocol.kUdpFieldNumber

        stream.protocol.add().protocol_id.id = ost_pb.Protocol.kPayloadFieldNumber

        self._drone.modifyStream(port_stream_cfg)

        return stream

    def _prepare_streams(self, duration):

        # delete old streams
        for tx_port_config in self._tx_port_configs:
            stream_ids = self._drone.getStreamIdList(tx_port_config.port_id)
            for stream_id in stream_ids.stream_id:
                stream_ids = ost_pb.StreamIdList()
                stream_ids.port_id.CopyFrom(tx_port_config.port_id)
                stream_ids.stream_id.add().id = stream_id.id

                self._drone.deleteStream(stream_ids)

        for tx_port_config in self._tx_port_configs:
            tx_port_config.stream = self._prepare_stream(tx_port_config, duration)

    def _tx_config_by_port_id(self, id):

        for tx_config in self._tx_port_configs:

            if tx_config.port_id.id == id:
                return tx_config

        raise KeyError('TXConfig lookup failed - invalid or unknown port id {}'.format(id))

    def interface_statistics(self):

        return self._interface_statistics

    def _interface_stats_create(self):
        """
        there is an ugly impedance mismatch between the stats we can collect
        and the stats we need to dump to the database. well...
        """
        self._interface_statistics = []

        for stat in self._drone.getStats(self._tx_port_ids).port_stats:
            tx_port_config = self._tx_config_by_port_id(stat.port_id.id)

            if abs(tx_port_config.frames_total_calculated - stat.tx_pkts) > self._accepted_tx_diff:
                sys.stderr.write('{} failed to send all frames. calculated: {:<10}  send: {:<10} diff: {}\n'.format(
                    tx_port_config.interface_name,
                    tx_port_config.frames_total_calculated,
                    stat.tx_pkts,
                    tx_port_config.frames_total_calculated - stat.tx_pkts
                ))
                sys.exit(1)

            injector_stat = RXTXStats(tx_port_config.interface_name,
                                      stat.rx_bytes, stat.rx_pkts,
                                      stat.tx_bytes, stat.tx_pkts,
                                      is_mirror_port=False,
                                      is_mirrored_port=tx_port_config.is_mirrored_port,
                                      speed_mbit=tx_port_config.speed_mbit)

            self._interface_statistics.append(injector_stat)

        for stat in self._drone.getStats(self._rx_port_ids).port_stats:
            interface_name = self._interface_name_by_port_id(stat.port_id)

            mirror_stat = RXTXStats(interface_name,
                                    stat.rx_bytes, stat.rx_pkts,
                                    stat.tx_bytes, stat.tx_pkts,
                                    is_mirror_port=True,
                                    is_mirrored_port=False,
                                    speed_mbit=0)

            self._interface_statistics.append(mirror_stat)

    def run(self, duration=10):

        self._prepare_streams(duration)

        self._drone.clearStats(self._tx_port_ids)
        self._drone.clearStats(self._rx_port_ids)

        time.sleep(1)

        self._drone.startCapture(self._rx_port_ids)
        time.sleep(0.5)
        self._drone.startTransmit(self._tx_port_ids)

        time.sleep(duration + 1)

        self._drone.stopTransmit(self._tx_port_ids)
        time.sleep(0.5)
        self._drone.stopCapture(self._rx_port_ids)

        self._interface_stats_create()

    @staticmethod
    def _mbit_len_to_frames_per_sec(mbit, frame_len, duration_sec):
        """

        :param mbit:
        :param frame_len:
        :param duration_sec:
        :return: frames_per_second, total_frames
        """
        bytes_per_sec = (mbit * 1000 * 1000) / 8

        frames_per_sec = bytes_per_sec / frame_len

        return frames_per_sec, frames_per_sec * duration_sec


if __name__ == '__main__':
    OI = OstinatoInterface(rx_interface='eth3')

    '''
    1 -> 00:e0:ed:0b:dc:2a  eth0
    2 -> 00:e0:ed:0b:dc:2b  eth1
    3 -> 00:e0:ed:0b:dc:2c  eth2
    4 -> 00:e0:ed:0b:dc:2d  eth3  capture
    '''

    # eth0_2mbit_64bytes = TXPortConfig('eth0', 0x00e0ed0bdc2a, 0x00e0ed0bdc2b, 1000, 30)
    # eth1_0mbit_64bytes = TXPortConfig('eth1', 0x00e0ed0bdc2b, 0x00e0ed0bdc2a, 1000, 30)
    # eth2_2mbit_64bytes = TXPortConfig('eth2', 0x00e0ed0bdc2c, 0x00e0ed0bdc2a, 1000, 25)
    eth2_0_2mbit_64bytes = TXPortConfig('eth2', False, 0x00e0ed0bdc2c, 0x00e0ed0bdc2a, 100, 40)
    eth2_1_2mbit_64bytes = TXPortConfig('eth1', True, 0x00e0ed0bdc2b, 0x00e0ed0bdc2b, 100, 40)

    # OI.tx_port_config_add(eth0_2mbit_64bytes)
    # OI.tx_port_config_add(eth1_0mbit_64bytes)
    # OI.tx_port_config_add(eth2_2mbit_64bytes)
    OI.tx_port_config_add(eth2_0_2mbit_64bytes)
    OI.tx_port_config_add(eth2_1_2mbit_64bytes)

    OI.tx_ports_dump()

    OI.run(duration=1)
    time.sleep(1)
    OI.run(duration=1)

    for rx_tx_stat in OI.interface_statistics():
        print rx_tx_stat
