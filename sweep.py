%matplotlib qt
import io
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import qcodes as qc
from qcodes.dataset.measurements import Measurement
from IPython import display

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
    
    def follow_param(self, p, gain=1.0):
        self._params.append((p, gain))

    def follow_sr830(self, l, name=None, gain=1.0):
        self._sr830s.append((l, name, gain))

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
        return meas

    def _prepare_1d_plots(self, set_param):
        self._fig = plt.figure(figsize=(4*(2 + len(self._params) + len(self._sr830s)),4))
        grid = plt.GridSpec(4, 1 + len(self._params) + len(self._sr830s), hspace=0)
        self._setax = self._fig.add_subplot(grid[:, 0])
        self._setax.set_xlabel('Time (s)')
        self._setax.set_ylabel(f'{set_param.label} ({set_param.unit})')
        self._setaxline = self._setax.plot([], [])[0]

        self._paxs = []
        self._plines = []
        for i, (p, _) in enumerate(self._params):
            ax = self._fig.add_subplot(grid[:, 1 + i])
            ax.set_xlabel(f'{set_param.label} ({set_param.unit})')
            ax.set_ylabel(f'{p.label} ({p.unit})')
            self._paxs.append(ax)
            self._plines.append(ax.plot([], [])[0])

        self._laxs = []
        self._llines = []
        for i, (l, name, _) in enumerate(self._sr830s):
            ax0 = self._fig.add_subplot(grid[:-1, 1 + len(self._params) + i])
            ax0.set_ylabel(f'{name} (V)')
            fmt = ScalarFormatter()
            fmt.set_powerlimits((-3, 3))
            ax0.get_yaxis().set_major_formatter(fmt)
            self._laxs.append(ax0)
            self._llines.append(ax0.plot([], [])[0])
            ax1 = self._fig.add_subplot(grid[-1, 1 + len(self._params) + i], sharex=ax0)
            ax1.set_ylabel('Phase (°)')
            ax1.set_xlabel(f'{set_param.label} ({set_param.unit})')
            self._laxs.append(ax1)
            self._llines.append(ax1.plot([], [])[0])
            plt.setp(ax0.get_xticklabels(), visible=False)

        self._fig.tight_layout()
        self._fig.show()

    def _update_1d_setax(self, setpoint, t):
        self._setaxline.set_xdata(np.append(self._setaxline.get_xdata(), t))
        self._setaxline.set_ydata(np.append(self._setaxline.get_ydata(), setpoint))
        self._setax.relim()
        self._setax.autoscale_view()

    def _update_1d_param(self, i, setpoint, value):
        self._plines[i].set_xdata(np.append(self._plines[i].get_xdata(), setpoint))
        self._plines[i].set_ydata(np.append(self._plines[i].get_ydata(), value))
        self._paxs[i].relim()
        self._paxs[i].autoscale_view()

    def _update_1d_sr830(self, i, setpoint, x, y):
        self._llines[i*2].set_xdata(np.append(self._llines[i*2].get_xdata(), setpoint))
        self._llines[i*2].set_ydata(np.append(self._llines[i*2].get_ydata(), x))
        self._llines[i*2+1].set_xdata(np.append(self._llines[i*2+1].get_xdata(), setpoint))
        self._llines[i*2+1].set_ydata(np.append(self._llines[i*2+1].get_ydata(), np.arctan2(y, x) * 180 / np.pi))
        self._laxs[i*2].relim()
        self._laxs[i*2].autoscale_view()
        self._laxs[i*2+1].relim()
        self._laxs[i*2+1].autoscale_view()

    def _redraw_1d_plot(self):
        self._fig.tight_layout()
        self._fig.canvas.draw()
        plt.pause(0.001)

    def _display_1d_plot(self):
        b = io.BytesIO()
        self._fig.savefig(b, format='png')
        display.display(display.Image(data=b.getbuffer(), format='png'))

    def sweep(self, set_param, vals, inter_delay=None):
        if inter_delay is not None:
            d = len(vals)*inter_delay
            h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
            print(f'Minimum duration: {h}h {m}m {s}s')

        self._prepare_1d_plots(set_param)
        meas = self._create_measurement(set_param)
        with meas.run() as datasaver:
            t0 = time.monotonic()
            for setpoint in vals:
                t = time.monotonic() - t0
                set_param.set(setpoint)
                self._update_1d_setax(setpoint, t)

                if inter_delay is not None:
                    plt.pause(inter_delay)

                data = [
                    (set_param, setpoint),
                    ('time', t)
                ]
                for i, (p, gain) in enumerate(self._params):
                    v = p.get()
                    v = v / gain
                    data.append((p, v))
                    self._update_1d_param(i, setpoint, v)

                for i, (l, _, gain) in enumerate(self._sr830s):
                    _autorange_srs(l, 3)
                    x, y = l.snap('x', 'y')
                    x, y = x / gain, y / gain
                    data.extend([(l.X, x), (l.Y, y)])
                    self._update_1d_sr830(i, setpoint, x, y)

                datasaver.add_result(*data)
                
                self._redraw_1d_plot()

            d = time.monotonic() - t0
            h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
            print(f'Completed in: {h}h {m}m {s}s')

            self._display_1d_plot()