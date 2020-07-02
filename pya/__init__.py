from .Asig import Asig
from .Astft import Astft
from .Aspec import Aspec
from .Amfcc import Amfcc
from .Aserver import Aserver
from .Arecorder import Arecorder
from .Ugen import Ugen
from .version import __version__
from .helper import *
# from .helper.visualization import basicplots
from .backend import *


def startup(**kwargs):
    return Aserver.startup_default_server(**kwargs)


def shutdown(**kwargs):
    Aserver.shutdown_default_server(**kwargs)
