from sqlalchemy import create_engine, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import sessionmaker, relationship
import time

Base = declarative_base()


def _timestamp_now():
    return int(time.time())


class Device(Base):
    __tablename__ = 'devices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    created = Column(Integer, default=_timestamp_now)

    measurements = relationship("Measurement", backref="devices")

    def __repr__(self):
        return '<Device(id={}, name={}, created={}, measurements={}>'.format(
            self.id,
            self.name,
            self.created,
            self.measurements
        )


class Measurement(Base):
    __tablename__ = 'measurements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.id'))
    name = Column(String)

    duration = Column(Integer)

    measurement_configs = relationship("MeasurementConfig", backref="measurements")

    def __repr__(self):
        return '<Measurement(id={}, name={}, duration={}, measurement_configs={}>'.format(
            self.id,
            self.name,
            self.duration,
            self.measurement_configs
        )


class MeasurementConfig(Base):
    __tablename__ = 'measurement_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    measurement_id = Column(Integer, ForeignKey('measurements.id'))

    frame_len = Column(Integer, nullable=False)
    created = Column(Integer, default=_timestamp_now)

    bandwidth_upstream = Column(Integer, default=0)
    bandwidth_downstream = Column(Integer, default=0)

    mirror_stats = relationship("MirrorStat", backref="measurements")
    injector_stats = relationship("InjectorStat", backref="measurements")

    def __repr__(self):
        return '<MeasurementConfig(id={}, date_created={}, measurement_id={}, ' \
               'frame_len={}, bandwidth_upstream={}, bandwidth_downstream={}, ' \
               'mirror_stats={} injector_stats={}>'.format(
            self.id,
            self.created,
            self.measurement_id,
            self.bandwidth_upstream,
            self.bandwidth_downstream,
            self.frame_len,
            self.mirror_stats,
            self.injector_stats
        )


class MirrorStat(Base):
    __tablename__ = 'mirror_stats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    measurement_config_id = Column(Integer, ForeignKey('measurement_configs.id'))
    port_name = Column(String, nullable=False)
    rx_frames = Column(Integer, nullable=False)
    rx_bytes = Column(Integer, nullable=False)

    def __repr__(self):
        return '<MirrorStat(id={}, measurement_id={}, port_name={}, rx_frames={}, rx_bytes={}>'.format(
            self.id,
            self.measurement_config_id,
            self.port_name,
            self.rx_frames,
            self.rx_bytes
        )


class InjectorStat(Base):
    __tablename__ = 'injector_stats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    measurement_config_id = Column(Integer, ForeignKey('measurement_configs.id'))
    is_mirrored_port = Column(Boolean, default=False)
    port_name = Column(String, nullable=False)
    rx_frames = Column(Integer, nullable=False)
    rx_bytes = Column(Integer, nullable=False)
    tx_frames = Column(Integer, nullable=False)
    tx_bytes = Column(Integer, nullable=False)
    tx_speed_mbit = Column(Integer, nullable=False)

    def __repr__(self):
        return '<InjectorStat(id={}, measurement_id={}, is_mirrored_port={}, rx_frames={}, rx_bytes={}, tx_speed_mbit={}, tx_frames={}, tx_bytes={}>'.format(
            self.id,
            self.measurement_config_id,
            self.is_mirrored_port,
            self.rx_frames,
            self.rx_bytes,
            self.tx_speed_mbit,
            self.tx_frames,
            self.tx_bytes
        )


class MeasurementModel(object):
    def __init__(self, db_file, drop_database=False, verbose=False):
        self._engine = create_engine('sqlite:///{}'.format(db_file), echo=verbose)
        if drop_database:
            Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)

        self._session_builder = sessionmaker(bind=self._engine)
        self._session = self._session_builder()

    def insert(self, obj):
        self._session.add(obj)
        self._session.commit()

    def measurements(self):
        return self._session.query(Measurement).all()

    @staticmethod
    def _bandwidth_total(measurement_config, from_mirrored_ports=False):

        total_bandwidth = 0
        for injector_stat in measurement_config.injector_stats:
            if injector_stat.is_mirrored_port == from_mirrored_ports:
                total_bandwidth += injector_stat.tx_speed_mbit

        return total_bandwidth

    @staticmethod
    def bandwidth_total_upstream(measurement_config):
        """
        bandwidth from mirrored port(s) to other ports
        """

        return MeasurementModel._bandwidth_total(measurement_config, from_mirrored_ports=True)

    @staticmethod
    def bandwidth_total_downstream(measurement_config):
        """
        bandwidth from other port(s) to mirrored port(s)
        """

        return MeasurementModel._bandwidth_total(measurement_config, from_mirrored_ports=False)

    @staticmethod
    def mirror_dropped(measurement_config):
        """
        calculate number of dropped frames between injector ports and mirror port
        sum(injector_ports.tx_frames) - sum(mirror_ports.rx_frames)
        :param measurement_config: to calculate the drops for
        :return: frames_dropped_total, frames_dropped_percent
        """
        mirror_rx_frames_total = 0
        injector_tx_frames_total = 0
        for mirror_stat in measurement_config.mirror_stats:
            mirror_rx_frames_total += mirror_stat.rx_frames

        for injector_stat in measurement_config.injector_stats:
            injector_tx_frames_total += injector_stat.tx_frames

        dropped_frames_total = abs(injector_tx_frames_total - mirror_rx_frames_total)
        dropped_frames_percent = (100.0 / injector_tx_frames_total) * dropped_frames_total
        return dropped_frames_total, dropped_frames_percent

    @staticmethod
    def upstream_downstream_dropped(measurement_config):
        """
        calculate number of dropped frames between injector ports
        upstream - sum(mirrored_injector_ports.tx_frames) - sum(non_mirrored_injector_ports.rx_frames)
        downstream - sum(non_mirrored_injector_ports.tx_frames) - sum(mirrored_injector_ports.rx_frames)
        :param measurement_config: to calculate the drops for
        :return: upstream_frames_dropped_total, upstream_frames_dropped_percent, downstream_frames_dropped_total, downstream_frames_dropped_percent
        """
        mirrored_tx_frames_total = 0
        mirrored_rx_frames_total = 0
        non_mirrored_tx_frames_total = 0
        non_mirrored_rx_frames_total = 0

        for injector_stat in measurement_config.injector_stats:

            if injector_stat.is_mirrored_port:
                mirrored_tx_frames_total += injector_stat.tx_frames
                mirrored_rx_frames_total += injector_stat.rx_frames
            else:
                non_mirrored_tx_frames_total += injector_stat.tx_frames
                non_mirrored_rx_frames_total += injector_stat.rx_frames

        if non_mirrored_tx_frames_total:
            upstream_frames_dropped_total = abs(mirrored_tx_frames_total - non_mirrored_rx_frames_total)
            upstream_frames_dropped_percent = (100.0 / mirrored_tx_frames_total) * upstream_frames_dropped_total
            downstream_frames_dropped_total = abs(non_mirrored_tx_frames_total - mirrored_rx_frames_total)
            downstream_frames_dropped_percent = (100.0 / non_mirrored_tx_frames_total) * downstream_frames_dropped_total
        else:
            # no non-mirrored tx interfaces - no drops :
            upstream_frames_dropped_total = 0
            upstream_frames_dropped_percent = 0.
            downstream_frames_dropped_total = 0
            downstream_frames_dropped_percent = 0.

        return upstream_frames_dropped_total, upstream_frames_dropped_percent, \
               downstream_frames_dropped_total, downstream_frames_dropped_percent

    def device_by_name(self, name):

        try:
            return self._session.query(Device).filter(Device.name == name)[0]
        except:
            raise KeyError('Unknown or invalid device name \'{}\''.format(name))

    def device_measurement_by_name(self, device, name):

        for measurement in device.measurements:
            if measurement.name == name:
                return measurement

        raise KeyError('invalid or unknown measurement \'{}\' in device \'{}\''.format(name, device))

    def measurement_config_by_frame_len(self, measurement, frame_len):

        for measurement_config in measurement.measurement_configs:
            if measurement_config.frame_len == frame_len:
                return measurement_config

        raise KeyError(
            'invalid or unknown config-frame_len \'{}\' in measurement \'{}\''.format(frame_len, measurement))

    def devices(self, filter_name=None):

        return [device.name for device in self._session.query(Device).all() if
                device.name == filter_name or (not filter_name) or filter_name == 'all']

    def device_by_name(self, name):

        for device in self._session.query(Device).all():
            if name == device.name:
                return device

        raise KeyError('invalid or unknown device name \'{}\''.format(name))

    def commit(self):
        self._session.commit()


if __name__ == '__main__':
    mm = MeasurementModel('/tmp/test.sqlite', drop_database=True)

    device = Device(name='test-switch')
    mm.insert(device)

    measurement = Measurement(device_id=device.id, name='test data')
    mm.insert(measurement)

    measurement_config = MeasurementConfig(measurement_id=measurement.id, frame_len=765)
    mm.insert(measurement_config)

    mirror_stat = MirrorStat(measurement_config_id=measurement_config.id, port_name='eth3', rx_frames=20,
                             rx_bytes=1022)

    injector_stat_0 = InjectorStat(measurement_config_id=measurement_config.id, port_name='eth2',
                                   rx_frames=1, rx_bytes=2,
                                   tx_frames=15, tx_bytes=4,
                                   tx_speed=5,
                                   is_mirrored_port=True
                                   )
    injector_stat_1 = InjectorStat(measurement_config_id=measurement_config.id, port_name='eth4',
                                   rx_frames=6, rx_bytes=7,
                                   tx_frames=8, tx_bytes=9,
                                   tx_speed=10
                                   )
    injector_stat_2 = InjectorStat(measurement_config_id=measurement_config.id, port_name='eth5',
                                   rx_frames=11, rx_bytes=12,
                                   tx_frames=13, tx_bytes=14,
                                   tx_speed=15
                                   )

    mm.insert(mirror_stat)
    mm.insert(injector_stat_0)
    mm.insert(injector_stat_1)
    mm.insert(injector_stat_2)

    # print measurement

    assert (MeasurementModel.bandwidth_total_downstream(measurement.measurement_configs[0]) == 25)
    assert (MeasurementModel.bandwidth_total_upstream(measurement.measurement_configs[0]) == 5)
    assert (MeasurementModel.mirror_dropped(measurement.measurement_configs[0]) == (16, 44.44444444444444))
    assert (MeasurementModel.upstream_downstream_dropped(measurement.measurement_configs[0]) ==
            (2, 13.333333333333334, 20, 95.23809523809524))

    test_switch = mm.device_by_name('test-switch')
    measurement = mm.device_measurement_by_name(device, 'test data')
