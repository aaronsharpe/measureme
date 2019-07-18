import time

import numpy as np
import qcodes as qc
from qcodes.dataset.measurements import Measurement
from qcodes.instrument_drivers.stanford_research.SR830 import SR830


def _sec_to_str(d):
    h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
    return f'{h}h {m}m {s}s'


def _autorange_srs(srs, max_changes=1):
    def autorange_once():
        r = srs.R.get()
        sens = srs.sensitivity.get()
        if r > 0.9 * sens:
            return srs.increment_sensitivity()
        elif r < 0.1 * sens:
            return srs.decrement_sensitivity()
        return False
    sets = 0
    while autorange_once() and sets < max_changes:
        sets += 1
        time.sleep(10*srs.time_constant.get())


class Sweep(object):
    def __init__(self):
        self._sr830s = []
        self._params = []
        self._fbl = None
        self._fbl_channels = []
        self._fbl_gains = None
    
    def follow_param(self, p, gain=1.0):
        self._params.append((p, gain))

    def follow_sr830(self, l, gain=1.0, autorange=True):
        self._sr830s.append((l, gain, autorange))
        
    def follow_fbl(self, fbl, channels, gains=None):
        self._fbl = fbl
        self._fbl_channels = channels
        self._fbl_gains = gains

    def _create_measurement(self, *set_params):
        meas = Measurement()
        for p in set_params:
            meas.register_parameter(p)
        meas.register_custom_parameter('time', label='Time', unit='s')
        for p, _ in self._params:
            meas.register_parameter(p, setpoints=(*set_params, 'time',))
        for l, _, _ in self._sr830s:
            meas.register_parameter(l.X, setpoints=(*set_params, 'time',))
            meas.register_parameter(l.Y, setpoints=(*set_params, 'time',))
        for c in self._fbl_channels:
            meas.register_custom_parameter(f'fbl_c{c}_x', label=f'FBL Channel {c} X', unit='V')
            meas.register_custom_parameter(f'fbl_c{c}_p', label=f'FBL Channel {c} Phase', unit='deg')
        return meas

    def sweep(self, set_param, vals, inter_delay=None):
        if inter_delay is not None:
            print(f'Minimum duration: {_sec_to_str(len(vals) * inter_delay)}')

        try:
            meas = self._create_measurement(set_param)
            with meas.run() as datasaver:
                t0 = time.monotonic()
                for setpoint in vals:
                    t = time.monotonic() - t0
                    set_param.set(setpoint)

                    if inter_delay is not None:
                        time.sleep(inter_delay)

                    data = [
                        (set_param, setpoint),
                        ('time', t)
                    ]

                    if self._fbl is not None:
                        d = self._fbl.get_v_in(self._fbl_channels)
                        for i, (c, (r, theta)) in enumerate(zip(self._fbl_channels, d)):
                            if self._fbl_gains is not None:
                                r = r / self._fbl_gains[i]
                            data.extend([(f'fbl_c{c}_r', r), (f'fbl_c{c}_p', theta)])

                    for i, (p, gain) in enumerate(self._params):
                        v = p.get()
                        v = v / gain
                        data.append((p, v))

                    for i, (l, gain, autorange) in enumerate(self._sr830s):
                        if autorange:
                            _autorange_srs(l, 3)
                        x, y = l.snap('x', 'y')
                        x, y = x / gain, y / gain
                        data.extend([(l.X, x), (l.Y, y)])

                    datasaver.add_result(*data)
        except KeyboardInterrupt:
            print('Interrupted.')
        print(f'Completed in: {_sec_to_str(time.monotonic() - t0)}')

    def watch(self, max_duration=None, inter_delay=None):
        try:
            meas = self._create_measurement()
            with meas.run() as datasaver:
                t0 = time.monotonic()
                t = time.monotonic() - t0
                while max_duration is None or t < max_duration:
                    t = time.monotonic() - t0

                    if inter_delay is not None:
                        time.sleep(inter_delay)

                    data = [('time', t)]

                    for i, (p, gain) in enumerate(self._params):
                        v = p.get()
                        v = v / gain
                        data.append((p, v))

                    for i, (l, gain, autorange) in enumerate(self._sr830s):
                        if autorange:
                            _autorange_srs(l, 3)
                        x, y = l.snap('x', 'y')
                        x, y = x / gain, y / gain
                        data.extend([(l.X, x), (l.Y, y)])
                        
                    if self._fbl is not None:
                        d = self._fbl.get_v_in(self._fbl_channels)
                        for i, (c, (r, theta)) in enumerate(zip(self._fbl_channels, d)):
                            if self._fbl_gains is not None:
                                r = r / self._fbl_gains[i]
                            data.extend([(f'fbl_c{c}_r', r), (f'fbl_c{c}_p', theta)])

                    datasaver.add_result(*data)
        except KeyboardInterrupt:
            print('Interrupted.')
        print(f'Completed in: {_sec_to_str(time.monotonic() - t0)}')

    def megasweep(self, s_fast, v_fast, s_slow, v_slow, inter_delay=None):
        if inter_delay is not None:
            print(f'Minimum duration: {_sec_to_str(len(v_fast) * len(v_slow) * inter_delay)}')

        t0 = time.monotonic()
        meas = self._create_measurement(s_fast, s_slow)
        try:
            with meas.run() as datasaver:
                for sp_slow in v_slow:
                    s_slow.set(sp_slow)

                    for sp_fast in v_fast:
                        t = time.monotonic() - t0
                        s_fast.set(sp_fast)

                        if inter_delay is not None:
                            time.sleep(inter_delay)

                        data = [
                            (s_slow, sp_slow),
                            (s_fast, sp_fast),
                            ('time', t)
                        ]
                        for i, (p, gain) in enumerate(self._params):
                            v = p.get()
                            v = v / gain
                            data.append((p, v))

                        for i, (l, gain, autorange) in enumerate(self._sr830s):
                            if autorange:
                                _autorange_srs(l, 3)
                            x, y = l.snap('x', 'y')
                            x, y = x / gain, y / gain
                            data.extend([(l.X, x), (l.Y, y)])

                        datasaver.add_result(*data)
        except KeyboardInterrupt:
            print('Interrupted.')
        print(f'Completed in: {_sec_to_str(time.monotonic() - t0)}')


def sweep1d(instr, start, end, step, delay, params):
    # Example: sweep1D(Vg, 0, 1, 0.1, 0.5, [srs1, srs2, [FBL, 0, 1, 2, 10, 11]])
    s = Sweep()
    for p in params:
        if isinstance(p, SR830):
            s.follow_sr830(p,p.name)
        elif p is list and p[0].name == ' FBL':
            # TODO: Need to do better in the future.
            channels = p[1:]
            s.follow_fbl(channels)
        else:
            s.follow_param(p)
    s.sweep(instr, np.arange(start, end, step), inter_delay=delay)
