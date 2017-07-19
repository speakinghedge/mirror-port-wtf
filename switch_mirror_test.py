from measurement_model import *
from ostinato_interface import *
import argparse
from interface_config import *
from traffic_config import *


def persist_stats(db_file, device_name, speed_pattern_set_name, duration, frame_len, stats):
    mm = MeasurementModel(db_file, drop_database=False)

    try:
        device = mm.device_by_name(device_name)
    except KeyError as _:
        device = Device(name=device_name)
        mm.insert(device)

    try:
        measurement = mm.device_measurement_by_name(device, speed_pattern_set_name)
    except KeyError as _:
        measurement = Measurement(device_id=device.id,
                                  name=speed_pattern_set_name,
                                  duration=duration)
        mm.insert(measurement)

    measurement_config = MeasurementConfig(measurement_id=measurement.id, frame_len=frame_len)
    mm.insert(measurement_config)

    for stat in stats:

        if stat.is_mirror_port:

            stat_entry = MirrorStat(measurement_config_id=measurement_config.id,
                                    port_name=stat.interface_name,
                                    rx_frames=stat.rx_frames,
                                    rx_bytes=stat.rx_bytes)
        else:

            stat_entry = InjectorStat(measurement_config_id=measurement_config.id,
                                      port_name=stat.interface_name,
                                      is_mirrored_port=stat.is_mirrored_port,
                                      rx_frames=stat.rx_frames,
                                      rx_bytes=stat.rx_bytes,
                                      tx_frames=stat.tx_frames,
                                      tx_bytes=stat.tx_bytes,
                                      tx_speed_mbit=stat.speed_mbit,
                                      )
        mm.insert(stat_entry)
    bandwidth_upstream = mm.bandwidth_total_upstream(measurement_config)
    bandwidth_downstream = mm.bandwidth_total_downstream(measurement_config)

    measurement_config.bandwidth_upstream = bandwidth_upstream
    measurement_config.bandwidth_downstream = bandwidth_downstream
    mm.commit()

    mirror_drop_frames, mirror_drop_percent = mm.mirror_dropped(measurement_config)

    upstream_frames_dropped_total, upstream_frames_dropped_percent, \
    downstream_frames_dropped_total, downstream_frames_dropped_percent = mm. upstream_downstream_dropped(
        measurement_config)

    print 'device: {:<10}, set_name: {:<10}, frame_len: {:<4}, ' \
          'speed_up: {:<3}, speed_down: {:<3}, speed_tot: {:<3}, ' \
          'mirror_drop: {:<8}, mirror_drop_percent: {:<3.3}, ' \
          'upstream_drop: {:<8}, upstream_drop_percent: {:<3.3}, ' \
          'downstream_drop: {:<8} downstream_drop_percent: {:<3.3}'.format(
        device_name,
        speed_pattern_set_name,
        frame_len,
        bandwidth_upstream,
        bandwidth_downstream,
        bandwidth_upstream + bandwidth_downstream,
        mirror_drop_frames,
        mirror_drop_percent,
        upstream_frames_dropped_total,
        upstream_frames_dropped_percent,
        downstream_frames_dropped_total,
        downstream_frames_dropped_percent
    )


def build_setup(oi, speed_pattern, frame_len):
    for idx, speed_mbit in enumerate(speed_pattern):

        if idx == 0:
            interface_name = TX_INTERFACES[0]
            port_config = TXPortConfig(interface_name,
                                       is_mirrored(interface_name),
                                       INTERFACE_MACS[interface_name],
                                       INTERFACE_MACS[TX_INTERFACES[1]],
                                       frame_len, speed_mbit)
        else:
            interface_name = TX_INTERFACES[idx]
            port_config = TXPortConfig(interface_name,
                                       is_mirrored(interface_name),
                                       INTERFACE_MACS[interface_name],
                                       INTERFACE_MACS[TX_INTERFACES[0]],
                                       frame_len, speed_mbit)

        oi.tx_port_config_add(port_config)


def is_mirrored(interface_name):
    return interface_name in MIRORRED_INTERFACES


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='mirror/bandwidth test tool')

    parser.add_argument('-d', '--dut-name', default='test', help='device under test name (default: test)')
    mutual_exclusive_group = parser.add_mutually_exclusive_group(required=True)
    mutual_exclusive_group.add_argument('-f', '--db-file', type=str, help='sqlite database to be used')
    mutual_exclusive_group.add_argument('-l', '--list-speed-pattern-sets', default=False, action='store_true',
                                        help='list available speed pattern sets')
    parser.add_argument('-s', '--speed-pattern-set', default=None,
                        help='select speed pattern set to be run (default: run all)')
    parser.add_argument('-v', '--verbose', default=False, action='store_true', help='show extended information')

    args = parser.parse_args()
    db_file = args.db_file
    dut_name = args.dut_name
    verbose = args.verbose
    selected_speed_pattern_set = args.speed_pattern_set

    if args.list_speed_pattern_sets:
        for speed_pattern_set_name in SPEED_PATTERN_SETS:
            print speed_pattern_set_name

        sys.exit(0)

    if selected_speed_pattern_set:

        try:
            active_speed_pattern_sets = {selected_speed_pattern_set:SPEED_PATTERN_SETS[selected_speed_pattern_set]}
        except KeyError as _:
            sys.stderr.write('Invalid or unknown speed pattern name \'{}\'. Abort.\n'.format(selected_speed_pattern_set))
            sys.exit(1)
    else:
        active_speed_pattern_sets = SPEED_PATTERN_SETS

    for speed_pattern_set_name in active_speed_pattern_sets:

        if verbose:
            print '{}'.format(speed_pattern_set_name)

        for frame_len in FRAME_SIZES:
            if verbose:
                print '\t{}'.format(frame_len)

            for speed_pattern in SPEED_PATTERN_SETS[speed_pattern_set_name]:
                if verbose:
                    print '\t\t{}'.format(speed_pattern)

                oi = OstinatoInterface(rx_interface=RX_INTERFACE)

                build_setup(oi, speed_pattern, frame_len)

                oi.run(duration=TIME_WARUMP)
                time.sleep(1)
                oi.run(duration=TIME_MEASURE)

                if verbose:
                    for rx_tx_stat in oi.interface_statistics():
                        print '\t\t\t{}'.format(rx_tx_stat)

                persist_stats(db_file, dut_name, speed_pattern_set_name, TIME_MEASURE, frame_len,
                              oi.interface_statistics())
