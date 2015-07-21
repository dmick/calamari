
"""
Wrap all our salt imports into one module.  We do this
to make it clear which parts of the salt API (or internals)
we are touching, and to make it easy to globally handle a
salt ImportError e.g. for building docs in lightweight
environment.
"""


import gevent
import logging

# used from multiple places; make the log simple
log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler())

def try_import(modsympairs, fail_value=None):
    '''
    modsympairs is an iterable of tuples (mod, sym)
    Try importing sym from mod; if sym contains 'as',
    assume it's 'rename_sym as sym'.
    If all imports fail, set sym to fail_value.
    '''
    for (mod, sym) in modsympairs:
        success = False
        try:
            if ' as ' in sym:
                rename_sym, sym = sym.split(' as ')
                tempmod = __import__(mod, globals(), locals(), list(rename_sym))
            else:
                tempmod = __import__(mod, globals(), locals(), list(sym))
            globals()[sym] = getattr(tempmod, sym)
            success = True
            break
        except (ImportError, AttributeError):
            pass

    if not success:
        log.warn("import %s failed unexpectedly" % sym)
        globals()[sym] = fail_value


try_import(
    (
        ('salt.client', 'condition_kwarg'),
        # Salt moved this in 382dd5e
        ('salt.utils.args', 'condition_input as condition_kwarg')
    ),
)
try_import((('salt.client', 'LocalClient'),))
try_import((('salt_utils.event', 'MasterEvent'),))
try_import((('salt.key', 'Key'),))
try_import((('salt.config', 'master_config'),))
try_import((('salt.utils.master', 'MasterPillarUtil'),))
try_import((('salt.config', 'client_config'),), lambda x: None)
try_import((('salt.loader', '_create_loader'),))


class SaltEventSource(object):
    """
    A wrapper around salt's MasterEvent class that closes and re-opens
    the connection if it goes quiet for too long, to ward off mysterious
    silent-death of communications (#8144)
    """

    # Not a logical timeout, just how long we stick inside a get_event call
    POLL_TIMEOUT = 5

    # After this long without messages, close and reopen out connection to
    # salt-master.  Don't want to do this gratuitously because it can drop
    # messages during the cutover (lossiness is functionally OK but user
    # might notice).
    SILENCE_TIMEOUT = 20

    def __init__(self, logger, config):
        """
        :param config: a salt client_config instance
        """
        # getChild isn't in 2.6
        self._log = logging.getLogger('.'.join((logger.name, 'salt')))
        self._silence_counter = 0
        self._config = config
        self._master_event = MasterEvent(self._config['sock_dir'])  # noqa

    def _destroy_conn(self, old_ev):
        old_ev.destroy()

    def get_event(self, *args, **kwargs):
        """
        Wrap MasterEvent.get_event
        """
        ev = self._master_event.get_event(self.POLL_TIMEOUT, *args, **kwargs)
        if ev is None:
            self._silence_counter += self.POLL_TIMEOUT
            if self._silence_counter > self.SILENCE_TIMEOUT:
                self._log.warning("Re-opening connection to salt-master")

                self._silence_counter = 0
                # Re-open the connection as a precaution against this lack of
                # messages being a symptom of a connection that has gone bad.
                old_ev = self._master_event
                gevent.spawn(lambda: self._destroy_conn(old_ev))
                self._master_event = MasterEvent(self._config['sock_dir'])  # noqa
        else:
            self._silence_counter = 0
            return ev
