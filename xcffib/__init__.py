import functools

from struct import unpack_from

from ffi import ffi, CONSTANTS, C

# re-export these constants for convenience and without hackery so pyflakes can
# work.
X_PROTOCOL = C.X_PROTOCOL
X_PROTOCOL_REVISION = C.X_PROTOCOL_REVISION

XCB_NONE = C.XCB_NONE
XCB_COPY_FROM_PARENT = C.XCB_COPY_FROM_PARENT
XCB_CURRENT_TIME = C.XCB_CURRENT_TIME
XCB_NO_SYMBOL = C.XCB_NO_SYMBOL

# For xpyb compatibility
NONE = XCB_NONE
CopyFromParent = XCB_COPY_FROM_PARENT
CurrentTime = XCB_CURRENT_TIME
NoSymbol = XCB_NO_SYMBOL

XCB_CONN_ERROR = C.XCB_CONN_ERROR
XCB_CONN_CLOSED_EXT_NOTSUPPORTED = C.XCB_CONN_CLOSED_EXT_NOTSUPPORTED
XCB_CONN_CLOSED_MEM_INSUFFICIENT = C.XCB_CONN_CLOSED_MEM_INSUFFICIENT
XCB_CONN_CLOSED_REQ_LEN_EXCEED = C.XCB_CONN_CLOSED_REQ_LEN_EXCEED
XCB_CONN_CLOSED_PARSE_ERR = C.XCB_CONN_CLOSED_PARSE_ERR
XCB_CONN_CLOSED_INVALID_SCREEN = C.XCB_CONN_CLOSED_INVALID_SCREEN
XCB_CONN_CLOSED_FDPASSING_FAILED = C.XCB_CONN_CLOSED_FDPASSING_FAILED

def popcount(n):
    return bin(n).count('1')

class XcffibException(Exception):
    """ Generic XcbException; replaces xcb.Exception. """
    pass

class ConnectionException(XcffibException):
    REASONS = {
        XCB_CONN_ERROR: (
            'xcb connection errors because of socket, '
            'pipe and other stream errors.'),
        XCB_CONN_CLOSED_EXT_NOTSUPPORTED: (
            'xcb connection shutdown because extension not supported'),
        XCB_CONN_CLOSED_MEM_INSUFFICIENT: (
            'malloc(), calloc() and realloc() error upon failure, '
            'for eg ENOMEM'),
        XCB_CONN_CLOSED_REQ_LEN_EXCEED: (
            'Connection closed, exceeding request length that server '
            'accepts.'),
        XCB_CONN_CLOSED_PARSE_ERR: (
            'Connection closed, error during parsing display string.'),
        XCB_CONN_CLOSED_INVALID_SCREEN: (
            'Connection closed because the server does not have a screen '
            'matching the display.'),
        XCB_CONN_CLOSED_FDPASSING_FAILED: (
            'Connection closed because some FD passing operation failed'),
    }

    def __init__(self, err):
        XcffibException.__init__(
            self, self.REASONS.get(err, "Unknown connection error."))

class ProtocolException(XcffibException):
    pass

class ExtensionKey(object):
    """ This definitely isn't needed, but we keep it around for compatibilty
    with xpyb.
    """
    def __init__(self, name):
        self.name = name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, o):
        return self.name == o.name

    def __ne__(self, o):
        return self.name != o.name

class Extension(object):
    # TODO: implement
    pass

class Protobj(object):

    """ Note: Unlike xcb.Protobj, this does NOT implement the sequence
    protocol. I found this behavior confusing: Protobj would implement the
    sequence protocol on self.buf, and then List would go and implement it on
    List. Additionally, as near as I can tell internally we only need the size
    of the buffer for cases when the size of things is unspecified. Thus,
    that's all we save.
    """

    def __init__(self, parent, offset, size=None):
        """
        Params:
        - parent: a bytes()
        - offset: the start of this offest in the bytes()
        - size: the size of this object (if none, then it is assumed to be
          len(parent))

        I don't actually think we need the size parameter here at all, but xpyb has
        it so we keep it around.
        """

        assert len(parent) < offset
        if size is not None:
            assert len(parent) > size + offset
        else:
            size = len(parent)
        self.bufsize = size - offset

class List(Protobj):
    def __init__(self, parent, offset, length, typ, size=-1):

        if size > 0:
            assert len(parent) > length * size + offset

        self.list = []
        cur = offset

        if isinstance(typ, str):
            count = length / size
            self.list = list(unpack_from(typ * count, parent, offset))
        else:
            while cur < size:
                item = typ(parent, cur)
                cur += item.bufsize
                self.list.append(item)

    def __len__(self):
        return len(self.list)
    # TODO: implement the rest of the sequence protocol

# These three are all empty.
class Struct(Protobj):
    pass

class Union(Protobj):
    pass

class VoidCookie(Protobj):
    pass

class Connection(object):

    # "Basic" functions in xcb, i.e. those which only take a connection and
    # return a primitive C type. These are added to connection just below the
    # class definition.
    BASIC_FUNCTIONS = [
        "has_error",
        "get_file_descriptor",
        "get_maximum_request_length",
        "prefetch_maximum_request_length",
        "flush",
        "generate_id",
        "disconnect",
    ]

    def __init__(self, display=None, fd=-1, auth=None):
        if auth is not None:
            c_auth = C.new("xcb_auth_info_t *")
            if C.xpyb_parse_auth(auth, len(auth), c_auth) < 0:
                raise XcffibException("invalid xauth")
        else:
            c_auth = C.NULL

        i = C.new("int *")

        if fd > 0:
            self._conn = C.xcb_connect_to_fd(fd, c_auth)
        elif c_auth != C.NULL:
            self._conn = C.xcb_connect_to_display_with_auth(display, c_auth, i)
        else:
            self._conn = C.xcb_connect(display, i)
        self.pref_screen = ffi.int(i)

        self.core = core(self)
        # TODO: xpybConn_setup

    def invalid(self):
        if self._conn is None:
            raise XcffibException("Invalid connection.")
        err = C.xcb_connection_has_error(self._conn)
        if err > 0:
            raise ConnectionException(err)

    @staticmethod
    def ensure_connected(f):
        """
        Check that the connection is valid both before and
        after the function is invoked.
        """
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            self = args[0]
            self.invalid()
            return f(*args, **kwargs)
            self.invalid()
        return wrapper

    @ensure_connected
    def get_setup(self):
        s = C.xcb_get_setup(self._conn)
        buf = ffi.buffer(s)

        global setup
        return setup(buf, 0)

    @ensure_connected
    def wait_for_event(self):
        # TODO: implement
        pass

    @ensure_connected
    def poll_for_event(self):
        # TODO: implement
        pass

for name in Connection.BASIC_FUNCTIONS:
    @Connection.ensure_connected
    def f(self):
        return getattr(C, "xcb_" + name)(self._conn)
    setattr(Connection, name, f)

class Event(Protobj):
    # TODO: implement
    pass

class Response(Protobj):
    # TODO: implement
    pass

class Error(Response, XcffibException):
    def __init__(self, parent, offset):
        Response.__init__(self, parent, offset)
        XcffibException.__init__(self)
        self.code = unpack_from('B', parent)

core = None
core_events = None
core_errors = None
setup = None

# This seems a bit over engineered to me; it seems unlikely there will ever be
# a core besides xproto, so why not just hardcode that?
def _add_core(value, setup, events, errors):
    if not isinstance(value, Extension):
        raise XcffibException("Extension type not derived from xcffib.Extension")
    if not isinstance(setup, Struct):
        raise XcffibException("Setup type not derived from xcffib.Struct")

    global core
    global core_events
    global core_errors
    global setup

    core = value
    core_events = events
    core_errors = errors
    setup = setup
