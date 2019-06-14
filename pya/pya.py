from .Aserver import Aserver
import numbers
from itertools import compress
import matplotlib.pyplot as plt
import numpy as np
import scipy.interpolate
import scipy.signal
from scipy.fftpack import fft, fftfreq, ifft
from scipy.io import wavfile
from .helpers import ampdb, dbamp, linlin, timeit
import logging
from copy import copy, deepcopy

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


class Asig:
    """Audio signal class.

    Parameters:
    ----------
    sig : numpy.array, str, int, float
        * numpy array as the audio signal
        * str as path to wave file. Currently only support .wav format. Will add more in future version
        * int creates a mono silent signal of sig samples
        * float creates a mono silent signal of sig seconds

    sr : int
        sampling rate

    label : str
        label for the member

    channels : int
        signal channels

    cn : list
        channels names, length needs to match the signal's channels

    Attributes:
    ----------
    sig : numpy array
        audio signal array

    sig_copy: numpy array (to be discussed or removed)
        a copy of the audio signal

    channels : int
        signal channels

    sr : int
        sampling rate

    samples : int
        length of signal

    cn : list
        channels names

    label : str
        label for the member

    """

    def __init__(self, sig, sr=44100, label="", channels=1, cn=None, copy="default"):
        self.sr = sr
        self.mix_mode = None
        self._ = {}  # dictionary for further return values
        if isinstance(sig, str):
            self.load_wavfile(sig)
        elif isinstance(sig, int):  # sample length
            if channels == 1:
                self.sig = np.zeros(sig).astype("float32")
            else:
                self.sig = np.zeros((sig, channels)).astype("float32")
        elif isinstance(sig, float):  # if float interpret as duration
            if channels == 1:
                self.sig = np.zeros(int(sig * sr)).astype("float32")
            else:
                self.sig = np.zeros((int(sig * sr), channels)).astype("float32")
        else:
            self.sig = np.array(sig).astype("float32")

        self.label = label
        # # make a copy for any processing events e.g. (panning, filtering)
        # # that needs to process the signal without permanent change.
        self.sig_copy = np.copy(self.sig)  # It takes around 100ms to copy a 17min audio at 44.1khz
        self.cn = cn
        self._set_col_names()
    #
    # def __copy__(self):
    #
    #     if copy == 'default':
    #         return self
    #
    #     elif copy == 'copy':
    #         cls = self.__class__
    #         result = cls.__new__(cls)
    #         result.__dict__.update(self.__dict__)
    #         return result

    # def __deepcopy__(self, memo):
    #     cls = self.__class__
    #     result = cls.__new__(cls)
    #     memo[id(self)] = result
    #     for k, v in self.__dict__.items():
    #         setattr(result, k, deepcopy(v, memo))
    #     return result



    @property
    def channels(self):
        try:
            return self.sig.shape[1]
        except IndexError:
            return 1

    @property
    def samples(self):  # Getter
        return np.shape(self.sig)[0]  # Update it.

    @property
    def cn(self):  # Channel names
        return self._cn

    @cn.setter
    def cn(self, val):
        if val is None:
            self._cn = None
        else:
            if len(val) == self.channels:
                if all(isinstance(x, str) for x in val):  # check if all elements are str
                    self._cn = val
                else:
                    raise TypeError("channel names cn need to be a list of string(s).")
            else:
                raise ValueError("list size doesn't match channel numbers {}".format(self.channels))

    def load_wavfile(self, fname):
        # Discuss to change to float32 .
        self.sr, self.sig = wavfile.read(fname)  # load the sample data
        if self.sig.dtype == np.dtype('int16'):
            self.sig = (self.sig / 32768.).astype('float32')

        elif self.sig.dtype != np.dtype('float32'):
            self.sig = self.sig.astype('float32')

        else:
            print("load_wavfile: TODO: add format")

    def save_wavfile(self, fname="asig.wav", dtype='float32'):
        if dtype == 'int16':
            data = (self.sig * 32767).astype('int16')
        elif dtype == 'int32':
            data = (self.sig * 2147483647).astype('int32')
        elif dtype == 'uint8':
            data = (self.sig * 127 + 128).astype('uint8')
        elif dtype == 'float32':
            data = self.sig.astype('float32')
        wavfile.write(fname, self.sr, data)
        return self

    def _set_col_names(self):
        # Problem is by doing that generating a new instance will no longer preserve cn.
        # TODO: discuss above problem with Jiajun,
        if self.cn is None:
            # TODO: set a meaningful list e.g. cn = [str(i) for i in range(self.channels)] instead of
            pass
        else:
            if type(self.cn[0]) is str:
                self.col_name = {self.cn[i]: i for i in range(len(self.cn))}
            else:
                raise TypeError("column names need to be a list of strings")

    def __getitem__(self, index):
        """ Perform numpy style slicing and time slicing and generate new asig.

        Parameters:
        ----------
        index : int, slice, list, tuple, dict
            Slicing argument. What are additional to numpy slicing:

            * Time slicing (unit in seconds) using dictionary asig[{1:2.5}] or asig[{1:2.5}, :]
            creates indexing of 1s to 2.5s.

            * Channel name slicing: asig['l'] returns channel 'l' as a new mono asig.
            asig[['front', 'rear']], etc...

        Returns:
        ----------
        Asig(sliced_signal, adjusted_sr, remarked_label, subset_channelnames)
        """
        if isinstance(index, tuple):
            _LOGGER.info(" getitem: index is tuple")
            rindex = index[0]
            cindex = index[1] if len(index) > 1 else None
        else:  # if only slice, list, dict, int or float given for row selection
            rindex = index
            cindex = None

        # parse row index rindex into ridx
        if isinstance(rindex, list):  # e.g. a[[4,5,7,8,9]], or a[[True, False, True...]]
            ridx = rindex
            sr = self.sr
        elif isinstance(rindex, int):  # picking a single row
            ridx = rindex
            _LOGGER.debug("integer slicing of index: %d", ridx)
            sr = self.sr
        elif isinstance(rindex, slice):
            _LOGGER.info(" getitem: row index is slice.")
            _, _, step = rindex.indices(len(self.sig))
            sr = int(self.sr / abs(step))
            ridx = rindex
        elif isinstance(rindex, dict):  # time slicing
            _LOGGER.info(" getitem: row index is dict. Time slicing.")
            for key, val in rindex.items():
                try:
                    start = int(key * self.sr)
                except TypeError:  # if it is None
                    start = None
                try:
                    stop = int(val * self.sr)
                except TypeError:
                    stop = None
            ridx = slice(start, stop, 1)
            sr = self.sr
            _LOGGER.debug("Time slicing, start: %s, stop: %s", str(start), str(stop))
        else:  # Dont think there is a usecase.
            ridx = rindex
            sr = self.sr

        # now parse cindex
        if type(cindex) is list:
            _LOGGER.info(" getitem: column index is list.")
            if isinstance(cindex[0], str):
                cidx = [self.col_name.get(s) for s in cindex]
                if cidx is None:
                    _LOGGER.error("Input column names does not exist")
                cn_new = [self.cn[i] for i in cidx] if self.cn is not None else None
            elif isinstance(cindex[0], bool):
                cidx = cindex
                cn_new = list(compress(self.cn, cindex))
            elif isinstance(cindex[0], int):
                cidx = cindex
                cn_new = [self.cn[i] for i in cindex] if self.cn is not None else None
        elif isinstance(cindex, int):
            _LOGGER.info(" getitem: column index is int.")
            cidx = cindex
            cn_new = [self.cn[cindex]] if self.cn is not None else None
        elif isinstance(cindex, slice):
            _LOGGER.info(" getitem: column index is slice.")
            cidx = cindex
            cn_new = self.cn[cindex] if self.cn is not None else None
        elif isinstance(cindex, str):  # if only a single channel name is given.
            cidx = self.col_name.get(cindex)
            cn_new = [cindex]
        else:  # if nothing is given, e.g. index = (ridx,) on calling a[:]
            cidx = slice(None, None, None)
            cn_new = self.cn
        # apply ridx and cidx and return result
        sig = self.sig[ridx, cidx] if self.channels > 1 else self.sig[ridx]

        # Squeezing shouldn't be performed here. this is because: a[:10, 0] and a[:10,[True, False]] return
        # (10,) and (10, 1) respectively. Which should be dealt with individually.
        if sig.ndim == 2 and sig.shape[1] == 1:
            if not isinstance(cindex[0], bool):  # Hot fix this to be consistent with bool slciing
                _LOGGER.debug("ndim is 2 and channel num is 1, performa np.squeeze")
                sig = np.squeeze(sig)
        if isinstance(sig, numbers.Number):
            _LOGGER.info("signal is scalar, convert to array")
            sig = np.array(sig)

        a = Asig(sig, sr=sr, label=self.label + '_arrayindexed', cn=cn_new)
        a.mix_mode = self.mix_mode
        return a

    # new setitem implementation (TH): in analogy to new __getitem__ and with mix modes
    # work in progress

    @property
    def x(self):
        self.mix_mode = 'extend'
        return self
    extend = x  # better readable synonym

    @property
    def b(self):
        self.mix_mode = 'bound'
        return self
    bound = b  # better readable synonym

    @property
    def o(self):
        self.mix_mode = 'overwrite'
        return self
    overwrite = o

    def __setitem__(self, index, value):
        """setitem: asig[index] = value.

        This allows all the methods from getitem:
            * Numpy style slicing
            * String/string_list slicing for subsetting channels based on channel name self.cn
            * time slicing (unit seconds) via dict.
        3 possible modes: (referring to asig as 'dest', and value as 'src'
            1. standard pythonic way that the src und dest dimensions need to match
                asig[...] = value
            2. bound mode where src is copied up to the bounds of src
                asig.b[...] = value
            3. extend mode where dest is dynamically extended to make space for src
                asig.x[...] = value
        Notes - Remarks - Bugs - ToDos:

        row index:
        - list [1,2,3,4,5,6,7,8] or [True, ..., False]
            -> list    -> b ok, no x

        - int 0
            -> int     -> allow both b and x?

        - slice 100:5000:2
            -> slice, see slice below

        - dict {0.5:2.5}
            -> slice
            * b should work, but should it truncate to stop or end of dest?
            * x only, if step==1 and stop=None

        for all 'x':
            what if int (resp. start) > self.samples? => extend beyond end
            but obviously not meaningful for += or *=, only set

        TODOs:
            a[50:60,0] = 4 -> 4 has no shape!! --> WORKS
            a[50:60,[0,1]] = [[1,3]] -> WORKS (broadcast_to)
            a[:,[0,1]] *= [[1,3] --> WORKS! but needs testing
            check if mix_mode copy required on each fn output: if yes implement
            check all sig = [[no numpy array]] cases
            a.x[300:,1:2] = 0.5*b with 1-ch b to 4-ch a: shape problem (600, ) to (600, 1)
        """
        # check if @property x or b used
        mode = self.mix_mode
        # print("mix_mode is:", mode)
        self.mix_mode = None  # reset when done

        if isinstance(index, tuple):
            rindex = index[0]
            cindex = index[1] if len(index) > 1 else None
        else:  # if only slice, list, dict, int or float given for row selection
            rindex = index
            cindex = None

        # parse row index rindex into ridx
        # sr = self.sr  # unused default case for conversion if not changed by special case
        if isinstance(rindex, list):  # e.g. a[[4,5,7,8,9]], or a[[True, False, True...]]
            ridx = rindex
        elif isinstance(rindex, int):  # picking a single row
            ridx = rindex
        elif isinstance(rindex, slice):
            _, _, step = rindex.indices(len(self.sig))
            sr = int(self.sr / abs(step))
            ridx = rindex
        elif isinstance(rindex, dict):  # time slicing
            for key, val in rindex.items():
                try:
                    start = int(key * self.sr)
                except TypeError:  # if it is None
                    start = None
                try:
                    stop = int(val * self.sr)
                except TypeError:
                    stop = None
            ridx = slice(start, stop, 1)
        else:  # Dont think there is a usecase.
            ridx = rindex

        # now parse cindex
        if type(cindex) is list:
            if isinstance(cindex[0], str):
                cidx = [self.col_name.get(s) for s in cindex]
                cidx = cidx[0] if len(cidx) == 1 else cidx  # hotfix for now.
            elif isinstance(cindex[0], bool):
                cidx = cindex
            elif isinstance(cindex[0], int):
                cidx = cindex
        elif isinstance(cindex, int) or isinstance(cindex, slice):  # int, slice are the same.
            cidx = cindex
        elif isinstance(cindex, str):  # if only a single channel name is given.
            cidx = self.col_name.get(cindex)
        else:
            cidx = slice(None)

        _LOGGER.debug("self.sig.ndim == %d", self.sig.ndim)
        if self.sig.ndim == 1:
            final_index = (ridx)
        else:
            final_index = (ridx, cidx)
        # apply setitem: set dest[ridx,cidx] = src return self

        if isinstance(value, Asig):
            _LOGGER.debug("value is asig")
            src = value.sig

        elif isinstance(value, np.ndarray):  # numpy array if not Asig, default: sr fits
            _LOGGER.debug("value is ndarray")
            src = value

        elif isinstance(value, list):  # if list
            _LOGGER.debug("value is list")
            src = value     # np.array(value)
            mode = None   # for list (assume values for channels), mode makes no sense...
            # TODO: check if useful behavior also for numpy arrays
        else:
            _LOGGER.debug("value not asig, ndarray, list")
            src = value
            mode = None  # for scalar types, mode makes no sense...
        # TODO: test correct treatment for non-np.array value

        # now execute according to mode (which is one of (None, 'bound', 'extend'))
        # print(f"{mode} mode: dest = {self.sig[ridx, cidx].shape}, src = {src.shape}")

        if mode is None:
            _LOGGER.debug("Default setitem mode")
            # ToDo: adapt to enable src=number, or row vector for channel values
            if isinstance(src, numbers.Number):
                self.sig[final_index] = src
            elif isinstance(src, list):  # for multichannel signals that is value for each column
                self.sig[final_index] = src
            else:  # numpy array
                try:
                    self.sig[final_index] = np.broadcast_to(src, self.sig[final_index].shape)
                except ValueError:
                    # an error occurs in as[n] = as2[m].sig
                    # msg: cannot broadcast a non-scalar to a scalar array
                    self.sig[final_index] = src

        elif mode == 'bound':
            _LOGGER.debug("setitem bound mode")
            dshape = self.sig[final_index].shape
            dn = dshape[0]  # ToDo: howto get that faster from ridx alone?
            sn = src.shape[0]
            if sn > dn:
                # The original src[:dn,:] resulted error
                # ValueError: shape mismatch: value array of shape (1500,1,2)
                # could not be broadcast to indexing result of shape (2,1500)
                # When passing no.zeros(shape=(1500, 2))
                self.sig[final_index] = src[:dn] if len(dshape) == 1 else src[:dn, :]
            else:
                self.sig[final_index][:sn] = src if len(dshape) == 1 else src[:, :]

        elif mode == 'extend':
            _LOGGER.info("setitem extend mode")
            if isinstance(ridx, list):
                print("Asig.setitem Error: extend mode not available for row index list")
                return self
            if isinstance(ridx, slice):
                if ridx.step not in [1, None]:
                    print("Asig.setitem Error: extend mode only available for step-1 slices")
                    return self
                if ridx.stop is not None:
                    print("Asig.setitem Error: extend mode only available if stop is None")
                    return self
            dshape = self.sig[final_index].shape
            dn = dshape[0]  # ToDo: howto compute dn faster from ridx shape(self.sig) alone?
            sn = src.shape[0]
            if sn <= dn:  # same as bound, since src fits in
                # print(dshape, self.sig[final_index][:sn].shape, src.shape)
                self.sig[final_index][:sn] = np.broadcast_to(src, (sn,) + dshape[1:])
            elif sn > dn:
                # print("sn>dn shapes:", dshape, src[dn:].shape)
                self.sig[final_index] = src[:dn]
                # now extend by nn = sn-dn additional rows
                if dn > 0:
                    nn = sn - dn  # nr of needed additional rows
                    self.sig = np.r_[self.sig, np.zeros((nn,) + self.sig.shape[1:])]
                    self.sig[-nn:, cidx] = src[dn:]
                else:  # this is when start is beyond length of dest...
                    # print(ridx.start, sn, dn)
                    nn = ridx.start + sn
                    self.sig = np.r_[self.sig, np.zeros((nn - self.sig.shape[0],) + self.sig.shape[1:])]
                    self.sig[-sn:, cidx] = src

        elif mode == 'overwrite':
            start_idx = ridx.start if isinstance(ridx, slice) else 0  # Start index of the ridx,
            stop_idx = ridx.stop if isinstance(ridx, slice) else 0  # Stop index of the rdix
            # This mode is to replace a subset with an any given shape.
            _LOGGER.info("setitem replace mode")
            end = start_idx + src.shape[0]  # Where the end point of the newly insert signal should be.
            # Create a new signal
            # New row is: original samples + (new_signal_sample - the range to be replace)
            # This line is slow.
            sig = np.ndarray(shape=(self.sig.shape[0] + src.shape[0] - (stop_idx - start_idx), self.channels))
            if sig.ndim == 2 and sig.shape[1] == 1:
                sig = np.squeeze(sig)
            if isinstance(sig, numbers.Number):
                sig = np.array(sig)

            sig[:start_idx] = self.sig[:start_idx]  # Copy the first part over
            sig[start_idx:end] = src                       # The second part is the new signal
            sig[end:] = self.sig[stop_idx:]       # The final part is the remaining of self.sig
            self.sig = sig                                 # Update self.sig
        return self

    def resample(self, target_sr=44100, rate=1, kind='linear'):
        """Resample signal based on interpolation, can process multichannel"""
        times = np.arange(self.samples) / self.sr
        tsel = np.arange(np.floor(self.samples / self.sr * target_sr / rate)) * rate / target_sr
        if self.channels == 1:
            interp_fn = scipy.interpolate.interp1d(times, self.sig, kind=kind, assume_sorted=True,
                                                   bounds_error=False, fill_value=self.sig[-1])
            return Asig(interp_fn(tsel), target_sr,
                        label=self.label + "_resampled", cn=self.cn)
        else:
            new_sig = np.ndarray(shape=(int(self.samples / self.sr * target_sr / rate), self.channels))
            for i in range(self.channels):
                interp_fn = scipy.interpolate.interp1d(
                    times, self.sig[:, i], kind=kind, assume_sorted=True, bounds_error=False, fill_value=self.sig[-1, i])
                new_sig[:, i] = interp_fn(tsel)
            return Asig(new_sig, target_sr, label=self.label + "_resampled", cn=self.cn)

    def play(self, rate=1, **kwargs):
        """Play Asig audio via Aserver, using Aserver.default (if existing)
        kwargs are propagzated to Aserver:play (onset=0, out=0)
        IDEA/ToDo: allow to set server='stream' to create
          which terminates when finished using pyaudiostream
        """
        if 'server' in kwargs.keys():
            s = kwargs['server']
        else:
            s = Aserver.default
        if not isinstance(s, Aserver):
            _LOGGER.error("Asig.play: no default server running, nor server arg specified.")
            return
        if rate == 1 and self.sr == s.sr:
            asig = self
            print(asig)
        else:
            asig = self.resample(s.sr, rate)
            print(asig)
        s.play(asig, **kwargs)
        return self

    def route(self, out=0):
        """Route the signal to n channel. This method shifts the signal by out channels:

            * out = 0: does nothing as the same signal is being routed to the same position
            * out > 0: move channels of self.sig to channels out [,out+1,...]
        """
        if isinstance(out, int):
            # not optimized method here
            new_sig = np.zeros((self.samples, out + self.channels))

            _LOGGER.debug("Shift to channel %d, new signal has %d channels", out, new_sig.shape[1])
            if self.channels == 1:
                new_sig[:, out] = self.sig
            else:
                new_sig[:, out:(out + self.channels)] = self.sig
            _LOGGER.debug("Successfully assign signal to new_sig")
            if self.cn is None:
                new_cn = self.cn
            else:
                uname_list = ['unnamed' for i in range(out)]
                if isinstance(self.cn, list):
                    new_cn = uname_list + self.cn
                else:
                    new_cn = uname_list.append(self.cn)
            return Asig(new_sig, self.sr, label=self.label + '_routed', cn=new_cn)
        else:
            raise TypeError("Argument needs to be int")

    def mono(self, blend=None):
        """Mix channels to mono signal.

        Perform sig = np.sum(self.sig_copy * blend, axis=1)

        Parameters:
        ----------
        blend : list
            list of gain for each channel as a multiplier. Do nothing if signal is already mono, raise warning
            if len(blend) not equal to self.channels

        """
        # TODO: change code to accept empty cn - alternatively, make
        # sure that signals always get a default cn, see ToDo for Asig.__init__()
        if self.channels == 1:
            _LOGGER.warning("Signal is already mono")
            return self

        if blend is None:
            blend = np.ones(self.channels) / self.channels
        # Todo: add check for type number

        if len(blend) != self.channels:
            _LOGGER.warning("Asig.to_mono(): len(blend)=%d != %d=Asig.channels -> no action",
                            len(blend), self.channels)
            return self
        else:
            sig = np.sum(self.sig * blend, axis=1)
            col_names = [self.cn[np.argmax(blend)]] if self.cn is not None else None
            return Asig(sig, self.sr, label=self.label + '_blended', cn=col_names)

    def stereo(self, blend=None):
        """Blend any channel of signal to stereo.

        Usage: blend = [[list], [list]], e.g:

        Mix ch0,1,2 to the left channel with gain of 0.3 each, and ch0,1,2,3 to right with 0.25 gain

        asig[[0.3, 0.3, 0.3], [0.25, 0.25, 0.25 0.25]]

        """
        if blend is None:
            left, right = (1, 1)
        else:
            left = blend[0]
            right = blend[1]
        # [[0.1,0.2,0.3], [0.4,0.5,0.6]]
        if self.channels == 1:
            left_sig = self.sig * left
            right_sig = self.sig * right
            sig = np.stack((left_sig, right_sig), axis=1)
            return Asig(sig, self.sr, label=self.label + '_to_stereo', cn=self.cn)
        elif len(left) == self.channels and len(right) == self.channels:
            left_sig = np.sum(self.sig * left, axis=1)
            right_sig = np.sum(self.sig * right, axis=1)
            sig = np.stack((left_sig, right_sig), axis=1)
            return Asig(sig, self.sr, label=self.label + '_to_stereo', cn=self.cn)
        else:
            _LOGGER.warning("Arg needs to be a list of 2 lists for left right. e.g. a[[0.2, 0.3, 0.2],[0.5]:"
                            "Blend ch[0,1,2] to left and ch0 to right")
            return self

    def rewire(self, dic):
        """rewire channels:
            {(0, 1): 0.5}: move channel 0 to 1 then reduce gain to 0.5
        """
        max_ch = max(dic, key=lambda x: x[1])[1] + 1  # Find what the largest channel in the newly rewired is .
        if max_ch > self.channels:
            new_sig = np.zeros((self.samples, max_ch))
            new_sig[:, :self.channels] = self.sig
        else:
            new_sig = self.sig
        for key, val in dic.items():
            new_sig[:, key[1]] = self.sig[:, key[0]] * val
        return Asig(new_sig, self.sr, label=self.label + '_rewire', cn=self.cn)

    def pan2(self, pan=0.):
        """pan2 only creates output in stereo, mono will be copy to stereo,
        stereo works as it should, larger channel signal will only has 0 and 1 being changed.
        panning is based on constant power panning.

        gain multiplication is the main computation cost.
        :param pan: float. range -1. to 1.
        :return: Asig
        """
        pan = float(pan)
        if type(pan) is float:
            # Stereo panning.
            if pan <= 1. and pan >= -1.:
                angle = linlin(pan, -1, 1, 0, np.pi / 2.)
                gain = [np.cos(angle), np.sin(angle)]
                if self.channels == 1:
                    newsig = np.repeat(self.sig_copy, 2)  # This is actually quite slow
                    newsig_shape = newsig.reshape(-1, 2) * gain
                    new_cn = [self.cn, self.cn]
                    return Asig(newsig_shape, self.sr,
                                label=self.label + "_pan2ed", channels=2, cn=new_cn)
                else:
                    self.sig_copy[:, :2] *= gain
                    return Asig(self.sig_copy, self.sr, label=self.label + "_pan2ed", cn=self.cn)
            else:
                _LOGGER.warning("Scalar panning need to be in the range -1. to 1. nothing changed.")
                return self

    def norm(self, norm=1, dcflag=False):
        """Normalize signal"""
        if dcflag:
            self.sig = self.sig - np.mean(self.sig, 0)
        if norm <= 0:  # take negative values as level in dB
            norm = dbamp(norm)
        self.sig = norm * self.sig / np.max(np.abs(self.sig), 0)
        return self

    def gain(self, amp=None, db=None):
        """Apply gain in amplitude or dB"""
        if db:  # overwrites amp
            amp = dbamp(db)
            _LOGGER.debug("gain in dB: %f, in amp: %f", float(db), amp)
        elif not amp:  # default 1 if neither is given
            amp = 1
        return Asig(self.sig * amp, self.sr, label=self.label + "_scaled", cn=self.cn)

    def rms(self, axis=0):
        """Return signal's RMS"""
        return np.sqrt(np.mean(np.square(self.sig), axis))

    def plot(self, fn=None, offset=0, scale=1, **kwargs):
        """Display signal graph"""
        if fn:
            if fn == 'db':
                fn = lambda x: np.sign(x) * ampdb((abs(x) * 2 ** 16 + 1))
            elif not callable(fn):
                _LOGGER.warning("Asig.plot: fn is neither keyword nor function")
                return self
            plot_sig = fn(self.sig)
        else:
            plot_sig = self.sig
        if self.channels == 1 or (offset == 0 and scale == 1):
            self._['plot'] = plt.plot(np.arange(0, self.samples) / self.sr, plot_sig, **kwargs)
        else:
            p = []
            ts = np.linspace(0, self.samples / self.sr, self.samples)
            for i, c in enumerate(self.sig.T):
                p.append(plt.plot(ts, i * offset + c * scale, **kwargs))
                plt.xlabel("time [s]")
                if self.cn:
                    plt.text(0, (i + 0.1) * offset, self.cn[i])
        return self

    def get_duration(self):
        """Return duration in seconds"""
        return self.samples / self.sr

    def get_times(self):
        """Get time stamps for left-edge of sample-and-hold-signal"""
        return np.linspace(0, (self.samples - 1) / self.sr, self.samples)

    def __eq__(self, other):
        """Check if two asig objects have the same signal. But does not care about sr and others"""
        sig_eq = np.array_equal(self.sig, other.sig)
        sr_eq = self.sr == other.sr
        return sig_eq and sr_eq

    def __repr__(self):
        return "Asig('{}'): {} x {} @ {}Hz = {:.3f}s cn={}".format(
            self.label, self.channels, self.samples, self.sr, self.samples / self.sr,
            self.cn)

    def __mul__(self, other):
        selfsig = self.sig
        othersig = other.sig if isinstance(other, Asig) else other
        if isinstance(othersig, numbers.Number):
            return Asig(selfsig * othersig, self.sr, label=self.label + "_multiplied", cn=self.cn)
        else:
            if self.mix_mode is 'bound':
                if selfsig.shape[0] > othersig.shape[0]:
                    selfsig = selfsig[:othersig.shape[0]]
                elif selfsig.shape[0] < othersig.shape[0]:
                    othersig = othersig[:selfsig.shape[0]]
            return Asig(selfsig * othersig, self.sr, label=self.label + "_multiplied", cn=self.cn)

    def __rmul__(self, other):
        if isinstance(other, Asig):
            return Asig(self.sig * other.sig, self.sr, label=self.label + "_multiplied", cn=self.cn)
        else:
            return Asig(self.sig * other, self.sr, label=self.label + "_multiplied", cn=self.cn)

    def __add__(self, other):
        selfsig = self.sig
        othersig = other.sig if isinstance(other, Asig) else other
        if isinstance(othersig, numbers.Number):  # When other is just a scalar
            return Asig(selfsig + othersig, self.sr, label=self.label + "_added", cn=self.cn)
        else:
            if self.mix_mode is 'bound':
                try:
                    if selfsig.shape[0] > othersig.shape[0]:
                        selfsig = selfsig[:othersig.shape[0]]
                    elif selfsig.shape[0] < othersig.shape[0]:
                        othersig = othersig[:selfsig.shape[0]]
                except AttributeError:
                    pass  # When othersig is just a scalar not
            return Asig(selfsig + othersig, self.sr, label=self.label + "_added", cn=self.cn)

    def __radd__(self, other):
        if isinstance(other, Asig):
            return Asig(self.sig + other.sig, self.sr, label=self.label + "_added", cn=self.cn)
        else:
            return Asig(self.sig + other, self.sr, label=self.label + "_added", cn=self.cn)

    # TODO not checked.
    def find_events(self, step_dur=0.001, sil_thr=-20, sil_min_dur=0.1, sil_pad=[0.001, 0.1]):
        if self.channels > 1:
            print("warning: works only with 1-channel signals")
            return -1
        step_samples = int(step_dur * self.sr)
        sil_thr_amp = dbamp(sil_thr)
        sil_flag = True
        sil_min_steps = int(sil_min_dur / step_dur)
        if type(sil_pad) is list:
            sil_pad_samples = [int(v * self.sr) for v in sil_pad]
        else:
            sil_pad_samples = (int(sil_pad * self.sr), ) * 2

        event_list = []
        for i in range(0, self.samples, step_samples):
            rms = self[i:i + step_samples].rms()
            if sil_flag:
                if rms > sil_thr_amp:  # event found
                    sil_flag = False
                    event_begin = i
                    sil_count = 0
                    continue
            else:
                event_end = i
                if rms < sil_thr_amp:
                    sil_count += 1
                else:
                    sil_count = 0  # reset if there is outlier non-silence
                if sil_count > sil_min_steps:  # event ended
                    event_list.append([
                        event_begin - sil_pad_samples[0],
                        event_end - step_samples * sil_min_steps + sil_pad_samples[1]])
                    sil_flag = True
        self._['events'] = np.array(event_list)
        return self

    # TODO not checked.
    def select_event(self, index=None, onset=None):
        if 'events' not in self._:
            print('select_event: no events, return all')
            return self
        events = self._['events']
        if onset:
            index = np.argmin(np.abs(events[:, 0] - onset * self.sr))
        if index is not None:
            beg, end = events[index]
            print(beg, end)
            return Asig(self.sig[beg:end], self.sr, label=self.label + f"event_{index}", cn=self.cn)
        print('select_event: neither index nor onset given: return self')
        return self

    def fade_in(self, dur=0.1, curve=1):
        nsamp = int(dur * self.sr)
        if nsamp > self.samples:
            nsamp = self.samples
            print("warning: Asig too short for fade_in - adapting fade_in time")
        return Asig(np.hstack((self.sig[:nsamp] * np.linspace(0, 1, nsamp) ** curve, self.sig[nsamp:])),
                    self.sr, label=self.label + "_fadein", cn=self.cn)

    def fade_out(self, dur=0.1, curve=1):
        nsamp = int(dur * self.sr)
        if nsamp > self.samples:
            nsamp = self.samples
            print("warning: Asig too short for fade_out - adapting fade_out time")
        return Asig(np.hstack((self.sig[:-nsamp],
                               self.sig[-nsamp:] * np.linspace(1, 0, nsamp)**curve)),
                    self.sr, label=self.label + "_fadeout", cn=self.cn)

    def iirfilter(self, cutoff_freqs, btype='bandpass', ftype='butter', order=4,
                  filter='lfilter', rp=None, rs=None):
        Wn = np.array(cutoff_freqs) * 2 / self.sr
        b, a = scipy.signal.iirfilter(order, Wn, rp=rp, rs=rs, btype=btype, ftype=ftype)
        y = scipy.signal.__getattribute__(filter)(b, a, self.sig, axis=0)
        aout = Asig(y, self.sr, label=self.label + "_iir")
        aout._['b'] = b
        aout._['a'] = a
        return aout

    def plot_freqz(self, worN, **kwargs):
        w, h = scipy.signal.freqz(self._['b'], self._['a'], worN)
        plt.plot(w * self.sr / 2 / np.pi, ampdb(abs(h)), **kwargs)

    def add(self, sig, pos=None, amp=1, onset=None):
        if type(sig) == Asig:
            n = sig.samples
            sr = sig.sr
            sigar = sig.sig
            if sig.channels != self.channels:
                print("channel mismatch!")
                return -1
            if sr != self.sr:
                print("sr mismatch: use resample")
                return -1
        else:
            n = np.shape(sig)[0]
            sr = self.sr  # assume same sr as self
            sigar = sig
        if onset:   # onset overwrites pos, time has priority
            pos = int(onset * self.sr)
        if not pos:
            pos = 0  # add to begin if neither pos nor onset have been specified
        last = pos + n
        if last > self.samples:
            last = self.samples
            sigar = sigar[:last - pos]
        self.sig[pos:last] += amp * sigar
        return self

    def envelope(self, amps, ts=None, curve=1, kind='linear'):
        nsteps = len(amps)
        duration = self.samples / self.sr
        if nsteps == self.samples:
            sig_new = self.sig * amps ** curve
        else:
            if not ts:
                given_ts = np.linspace(0, duration, nsteps)
            else:
                if nsteps != len(ts):
                    print("Asig.envelope error: len(amps)!=len(ts)")
                    return self
                if all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)):  # if list is monotonous
                    if ts[0] > 0:  # if first t > 0 extend amps/ts arrays prepending item
                        ts = np.insert(np.array(ts), 0, 0)
                        amps = np.insert(np.array(amps), 0, amps[0])
                    if ts[-1] < duration:  # if last t < duration append amps/ts value
                        ts = np.insert(np.array(ts), -1, duration)
                        amps = np.insert(np.array(amps), -1, amps[-1])
                else:
                    print("Asig.envelope error: ts not sorted")
                    return self
                given_ts = ts
            if nsteps != self.samples:
                interp_fn = scipy.interpolate.interp1d(given_ts, amps, kind=kind)
                sig_new = self.sig * interp_fn(np.linspace(0, duration, self.samples)) ** curve  # ToDo: curve segmentwise!!!
        return Asig(sig_new, self.sr, label=self.label + "_enveloped", cn=self.cn)

    def adsr(self, att=0, dec=0.1, sus=0.7, rel=0.1, curve=1, kind='linear'):
        dur = self.get_duration()
        return self.envelope([0, 1, sus, sus, 0], [0, att, att + dec, dur - rel, dur],
                             curve=curve, kind=kind)

    def window(self, win='triang', **kwargs):
        if not win:
            return self
        winstr = win
        if type(winstr) == tuple:
            winstr = win[0]
        return Asig(self.sig * scipy.signal.get_window(
            win, self.samples, **kwargs), self.sr, label=self.label + "_" + winstr, cn=self.cn)

    def window_op(self, nperseg=64, stride=32, win=None, fn='rms', pad='mirror'):
        centerpos = np.arange(0, self.samples, stride)
        nsegs = len(centerpos)
        res = np.zeros((nsegs, ))
        for i, cp in enumerate(centerpos):
            i0 = cp - nperseg // 2
            i1 = cp + nperseg // 2
            if i0 < 0:
                i0 = 0   # ToDo: correct padding!!!
            if i1 >= self.samples:
                i1 = self.samples - 1  # ToDo: correct padding!!!
            if isinstance(fn, str):
                res[i] = self[i0:i1].window(win).__getattribute__(fn)()
            else:  # assume fn to be a function on Asig
                res[i] = fn(self[i0:i1])
        return Asig(np.array(res), sr=self.sr // stride, label='window_oped', cn=self.cn)

    def overlap_add(self, nperseg=64, stride_in=32, stride_out=32, jitter_in=None, jitter_out=None,
                    win=None, pad='mirror'):
        # TODO: check with multichannel ASigs
        # TODO: allow stride_in and stride_out to be arrays of indices
        # TODO: add jitter_in, jitter_out parameters to reduce spectral ringing effects
        res = Asig(np.zeros((self.samples // stride_in * stride_out, )), sr=self.sr,
                   label=self.label + '_ola', cn=self.cn)
        ii = 0
        io = 0
        for _ in range(self.samples // stride_in):
            i0 = ii - nperseg // 2
            if jitter_in:
                i0 += np.random.randint(jitter_in)
            i1 = i0 + nperseg
            if i0 < 0:
                i0 = 0  # TODO: correct left zero padding!!!
            if i1 >= self.samples:
                i1 = self.samples - 1  # ToDo: correct right zero padding!!!
            pos = io
            if jitter_out:
                pos += np.random.randint(jitter_out)
            res.add(self[i0:i1].window(win).sig, pos=pos)
            io += stride_out
            ii += stride_in
        return res

    def to_spec(self):
        return Aspec(self)

    def to_stft(self, **kwargs):
        return Astft(self, **kwargs)

    def spectrum(self):
        nrfreqs = self.samples // 2 + 1
        frq = np.linspace(0, 0.5 * self.sr, nrfreqs)  # one sides frequency range
        Y = fft(self.sig)[:nrfreqs]  # / self.samples
        return frq, Y

    def plot_spectrum(self, **kwargs):
        frq, Y = self.spectrum()
        plt.subplot(211)
        plt.plot(frq, np.abs(Y), **kwargs)
        plt.xlabel('freq (Hz)')
        plt.ylabel('|F(freq)|')
        plt.subplot(212)
        self._['lines'] = plt.plot(frq, np.angle(Y), 'b.', markersize=0.2)
        return self

    def spectrogram(self, *argv, **kvarg):
        freqs, times, Sxx = scipy.signal.spectrogram(self.sig, self.sr, *argv, **kvarg)
        return freqs, times, Sxx

    def size(self):
        # return samples and length in time:
        return self.sig.shape, self.sig.shape[0] / self.sr

    def vstack(self, chan):
        # Create multichannel signal from mono
        self.sig = np.vstack([self.sig] * chan)
        self.sig = self.sig.transpose()
        return self.overwrite(self.sig, self.sr)  # Overwrite the signal
        # TODO: replace this (old) overwrite by a hidden private _transplant_sig(ndarr, sr)
        # since overwrite is now a property for setitem...

    def custom(self, func, **kwargs):
        """custom function method."""
        func(self, **kwargs)
        return self


class Aspec:
    'audio spectrum class using rfft'

    def __init__(self, x, sr=44100, label=None, cn=None):
        self.cn = cn
        if type(x) == Asig:
            self.sr = x.sr
            self.rfftspec = np.fft.rfft(x.sig)
            self.label = x.label + "_spec"
            self.samples = x.samples
            self.channels = x.channels
            self.cn = x.cn
            if cn is not None and self.cn != cn:
                print("Aspec:init: given cn different from Asig cn: using Asig.cn")
        elif type(x) == list or type(x) == np.ndarray:
            self.rfftspec = np.array(x)
            self.sr = sr
            self.samples = (len(x) - 1) * 2
            self.channels = 1
            if len(np.shape(x)) > 1:
                self.channels = np.shape(x)[1]
        else:
            print("error: unknown initializer")
        if label:
            self.label = label
        self.nr_freqs = self.samples // 2 + 1
        self.freqs = np.linspace(0, self.sr / 2, self.nr_freqs)

    def to_sig(self):
        return Asig(np.fft.irfft(self.rfftspec), sr=self.sr, label=self.label + '_2sig', cn=self.cn)

    def weight(self, weights, freqs=None, curve=1, kind='linear'):
        nfreqs = len(weights)
        if not freqs:
            given_freqs = np.linspace(0, self.freqs[-1], nfreqs)
        else:
            if nfreqs != len(freqs):
                print("Aspec.weight error: len(weights)!=len(freqs)")
                return self
            if all(freqs[i] < freqs[i + 1] for i in range(len(freqs) - 1)):  # check if list is monotonous
                if freqs[0] > 0:
                    freqs = np.insert(np.array(freqs), 0, 0)
                    weights = np.insert(np.array(weights), 0, weights[0])
                if freqs[-1] < self.sr / 2:
                    freqs = np.insert(np.array(freqs), -1, self.sr / 2)
                    weights = np.insert(np.array(weights), -1, weights[-1])
            else:
                print("Aspec.weight error: freqs not sorted")
                return self
            given_freqs = freqs
        if nfreqs != self.nr_freqs:
            interp_fn = scipy.interpolate.interp1d(given_freqs, weights, kind=kind)
            rfft_new = self.rfftspec * interp_fn(self.freqs) ** curve  # ToDo: curve segmentwise!!!
        else:
            rfft_new = self.rfftspec * weights ** curve
        return Aspec(rfft_new, self.sr, label=self.label + "_weighted")

    def plot(self, fn=np.abs, xlim=None, ylim=None, **kwargs):
        plt.plot(self.freqs, fn(self.rfftspec), **kwargs)
        if xlim is not None:
            plt.xlim([xlim[0], xlim[1]])

        if ylim is not None:
            plt.ylim([ylim[0], ylim[1]])

        plt.xlabel('freq (Hz)')
        plt.ylabel(f'{fn.__name__}(freq)')
        return self


    def __repr__(self):
        return "Aspec('{}'): {} x {} @ {} Hz = {:.3f} s".format(
            self.label, self.channels, self.samples, self.sr, self.samples / self.sr)


# TODO, check with multichannel
class Astft:
    'audio spectrogram (STFT) class'

    def __init__(self, x, sr=None, label=None, window='hann', nperseg=256,
                 noverlap=None, nfft=None, detrend=False, return_onesided=True,
                 boundary='zeros', padded=True, axis=-1, cn=None):
        self.window = window
        self.nperseg = nperseg
        self.noverlap = noverlap
        self.nfft = nfft
        self.detrend = detrend
        self.return_onesided = return_onesided
        self.boundary = boundary
        self.padded = padded
        self.axis = axis
        self.cn = cn
        if type(x) == Asig:
            # TODO multichannel.
            self.sr = x.sr
            if sr:
                self.sr = sr  # explicitly given sr overwrites Asig
            self.freqs, self.times, self.stft = scipy.signal.stft(
                x.sig, fs=self.sr, window=window, nperseg=nperseg, noverlap=noverlap, nfft=nfft,
                detrend=detrend, return_onesided=return_onesided, boundary=boundary, padded=padded, axis=axis)
            self.label = x.label + "_stft"
            self.samples = x.samples
            self.channels = x.channels
        elif type(x) == np.ndarray and np.shape(x) >= 2:
            self.stft = x
            self.sr = 44100
            if sr:
                self.sr = sr
            self.samples = (len(x) - 1) * 2
            self.channels = 1
            if len(np.shape(x)) > 2:
                self.channels = np.shape(x)[2]
            # TODO: set other values, particularly check if self.times and self.freqs are correct
            self.ntimes, self.nfreqs, = np.shape(self.stft)
            self.times = np.linspace(0, (self.nperseg - self.noverlap) * self.ntimes / self.sr, self.ntimes)
            self.freqs = np.linspace(0, self.sr // 2, self.nfreqs)
        else:
            print("error: unknown initializer or wrong stft shape ")
        if label:
            self.label = label

    def to_sig(self, **kwargs):
        """ create signal from stft, i.e. perform istft, kwargs overwrite Astft values for istft
        """
        for k in ['sr', 'window', 'nperseg', 'noverlap', 'nfft', 'input_onesided', 'boundary']:
            if k in kwargs.keys():
                kwargs[k] = self.__getattribute__(k)

        if 'sr' in kwargs.keys():
            kwargs['fs'] = kwargs['sr']
            del kwargs['sr']

        _, sig = scipy.signal.istft(self.stft, **kwargs)  # _ since 1st return value 'times' unused
        return Asig(sig, sr=self.sr, label=self.label + '_2sig', cn=self.cn)

    def plot(self, fn=lambda x: x, ax=None, xlim=None, ylim=None, **kwargs):
        if ax is None:
            plt.pcolormesh(self.times, self.freqs, fn(np.abs(self.stft)), **kwargs)
            plt.colorbar()
            if ylim is not None:
                plt.ylim([ylim[0], ylim[1]])

        else:
            ax.pcolormesh(self.times, self.freqs, fn(np.abs(self.stft)), **kwargs)
            # plt.colorbar(ax=ax)
            if ylim is not None:
                ax.set_ylim(ylim[0], ylim[1])

        return self

    def __repr__(self):
        return "Astft('{}'): {} x {} @ {} Hz = {:.3f} s".format(
            self.label, self.channels, self.samples, self.sr, self.samples / self.sr, cn=self.cn)
