import argparse

import argparse as argparse
import os

import matplotlib
import sys

from measurement_model import MeasurementModel
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt

from mpl_toolkits.mplot3d import Axes3D
from matplotlib import cm
from matplotlib.colors import LightSource, LinearSegmentedColormap, Normalize
import matplotlib.pyplot as plt
import numpy as np


from traffic_config import SPEED_PATTERN_SETS


def _measurement_min_max(measurement_model, measurement):
    min_frame_len = sys.maxint
    max_frame_len = 0
    min_bandwidth = 0
    max_bandwidth = 0

    dropped_frames_total_max = 0
    dropped_frames_percent_max = 0.

    for measurement_config in measurement.measurement_configs:

        if measurement_config.frame_len < min_frame_len:
            min_frame_len = measurement_config.frame_len
        if measurement_config.frame_len > max_frame_len:
            max_frame_len = measurement_config.frame_len

        bandwidth_upstream = measurement_config.bandwidth_upstream
        bandwidth_downstream = measurement_config.bandwidth_downstream

        bandwidth_total = bandwidth_upstream + bandwidth_downstream

        if bandwidth_total > max_bandwidth:
            max_bandwidth = bandwidth_total

        dropped_frames_total, dropped_frames_percent = measurement_model.mirror_dropped(measurement_config)

        if dropped_frames_total > dropped_frames_total_max:
            dropped_frames_total_max = dropped_frames_total
            dropped_frames_percent_max = dropped_frames_percent

    return min_bandwidth, max_bandwidth, min_frame_len, max_frame_len, dropped_frames_total_max, dropped_frames_percent_max


def _build_cm(v_min, v_max):
    cdict1 = {'red': ((0.0, 0.0, 0.0),
                      (0.1, 0.8, 0.8),
                      (1.0, 1.0, 1.0)),

              'green': ((0.0, 1.0, 1.0),
                        (0.1, 0.8, 0.8),
                        (1.0, 0.0, 0.0)),
              'blue': ((0.0, 0.0, 0.0),
                       (1.0, 0.0, 0.0))
              }

    green_red = LinearSegmentedColormap('GreenRed', cdict1)

    norm = Normalize(vmin=v_min, vmax=v_max)

    return green_red, norm


def plot_measurement(measurement_model, device_name, measurement, show_graph, output_dir):
    fig = plt.figure(figsize=(15, 8))
    ax = fig.add_subplot(111, projection='3d')

    min_bandwidth, max_bandwidth, min_frame_len, max_frame_len, \
    dropped_frames_total_max, dropped_frames_percent_max = _measurement_min_max(measurement_model, measurement)

    green_red, norm = _build_cm(0, dropped_frames_percent_max)

    for measurement_config in measurement.measurement_configs:
        bandwidth_upstream = measurement_model.bandwidth_total_upstream(measurement_config)
        bandwidth_downstream = measurement_model.bandwidth_total_downstream(measurement_config)
        bandwidth_total = bandwidth_upstream + bandwidth_downstream
        _, drop_mirror_percent = measurement_model.mirror_dropped(measurement_config)

        a = bandwidth_total / float(max_bandwidth)

        ax.scatter(measurement_config.frame_len,
                   bandwidth_total,
                   drop_mirror_percent,
                   c=drop_mirror_percent,
                   alpha=a,
                   cmap=green_red,
                   norm=norm)

    ax.set_zlim(0, dropped_frames_percent_max)
    ax.set_xlabel('frame len / bytes')
    ax.set_ylabel('total bandwidth / Mbit/s')
    ax.set_zlabel('frames dropped / percent')
    ax.view_init(azim=-20., elev=20.)
    plt.title('{} @ {}'.format(device_name, measurement.name))

    if output_dir:
        fig.savefig(os.path.join(output_dir, '{}---{}.png'.format(device_name, measurement.name)), dpi=80)
    if show_graph:
        plt.show()


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='mirror/bandwidth test tool - data plotter')
    mutual_exclusive_group = parser.add_mutually_exclusive_group()
    parser.add_argument('-f', '--db-file', type=str, required=True, help='sqlite database to be used')
    parser.add_argument('-d', '--dut-name', default='all', help='device under test name (default: all => process all)')

    mutual_exclusive_group.add_argument('-L', '--list-dut-names', default=False, action='store_true',
                                        help='list available device under test names')
    mutual_exclusive_group.add_argument('-l', '--list-speed-pattern-sets', default=False, action='store_true',
                                        help='list available speed pattern sets')
    mutual_exclusive_group.add_argument('-s', '--speed-pattern-set', default=None,
                                        help='select speed pattern set to be plotted')
    mutual_exclusive_group.add_argument('-o', '--write-graphs-to-dir',
                                        help='if given, write generated graphs to given directory')
    mutual_exclusive_group.add_argument('-g', '--show-graph', default=False, action='store_true',
                                        help='show interactive window')
    parser.add_argument('-v', '--verbose', default=False, action='store_true', help='show extended information')

    args = parser.parse_args()
    db_file = args.db_file
    dut_name = args.dut_name
    verbose = args.verbose
    selected_speed_pattern_set = args.speed_pattern_set
    output_dir = args.write_graphs_to_dir
    show_graph = args.show_graph

    if args.list_dut_names:
        mm = MeasurementModel(db_file)
        print '\n'.join(mm.devices())
        sys.exit(0)

    if args.list_speed_pattern_sets:
        for speed_pattern_set_name in SPEED_PATTERN_SETS:
            print speed_pattern_set_name
        sys.exit(0)

    mm = MeasurementModel(db_file)

    device_names = mm.devices(filter_name=dut_name)

    if not len(device_names):
        sys.stderr.write('invalid or unknown DUT name filte: \'{}\'. Abort.\n'.format(dut_name))
        sys.exit(1)

    for device_name in device_names:

        device = mm.device_by_name(device_name)

        if selected_speed_pattern_set:
            measurement = mm.device_measurement_by_name(device, selected_speed_pattern_set)
            plot_measurement(mm, device_name, measurement, show_graph, output_dir)
        else:
            for measurement in device.measurements:
                plot_measurement(mm, device_name, measurement, show_graph, output_dir)
