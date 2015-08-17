#  _________________________________________________________________________
#
#  PyUtilib: A Python utility library.
#  Copyright (c) 2008 Sandia Corporation.
#  This software is distributed under the BSD License.
#  Under the terms of Contract DE-AC04-94AL85000 with Sandia Corporation,
#  the U.S. Government retains certain rights in this software.
#  _________________________________________________________________________

__all__ = ['get_nameserver','shutdown_pyro_components']

import os
import sys
import time
import random

from pyutilib.pyro import using_pyro3, using_pyro4
from pyutilib.pyro import Pyro as _pyro

if sys.version_info >= (3,0):
    xrange = range
    import queue as Queue
else:
    import Queue

def get_nameserver(host=None, num_retries=30, caller_name="Unknown"):

    if _pyro is None:
        raise ImportError("Pyro or Pyro4 is not available")

    timeout_upper_bound = 5.0

    if not host is None:
        os.environ['PYRO_NS_HOSTNAME'] = host
    elif 'PYRO_NS_HOSTNAME' in os.environ:
        host = os.environ['PYRO_NS_HOSTNAME']

    # Deprecated in Pyro3
    # Removed in Pyro4
    if using_pyro3:
        _pyro.core.initServer()

    ns = None

    if using_pyro3:
        connection_problem = _pyro.errors.ConnectionDeniedError
    else:
        connection_problem = _pyro.errors.TimeoutError
    for i in xrange(0, num_retries+1):
        try:
            if using_pyro3:
                if host is None:
                    ns = _pyro.naming.NameServerLocator().getNS()
                else:
                    ns = _pyro.naming.NameServerLocator().getNS(host)
            else:
                ns = _pyro.locateNS(host=host)
            break
        except _pyro.errors.NamingError:
            pass
        except connection_problem:
            # this can occur if the server is too busy.
            pass

        # we originally had a single sleep timeout value, hardcoded to 1 second.
        # the problem with this approach is that if a large number of concurrent
        # processes fail, then they will all re-attempt at roughly the same
        # time. causing more contention than is necessary / desirable. by randomizing
        # the sleep interval, we are hoping to distribute the number of clients
        # attempting to connect to the name server at any given time.
        # TBD: we should eventually read the timeout upper bound from an enviornment
        #      variable - to support cases with a very large (hundreds to thousands)
        #      number of clients.
        if i < num_retries:
            sleep_interval = random.uniform(1.0, timeout_upper_bound)
            print("%s failed to locate name server after %d attempts - trying again in %5.2f seconds." % (caller_name, i+1,sleep_interval))
            time.sleep(sleep_interval)

    if ns is None:
        print("%s could not locate nameserver (attempts=%d)" % (caller_name,num_retries+1))
        raise SystemExit

    return ns

def get_dispatchers(group=":PyUtilibServer",
                    host=None,
                    num_dispatcher_tries=30,
                    min_dispatchers=1,
                    caller_name=None,
                    ns=None):

    if ns is None:
        ns = get_nameserver(host, caller_name=caller_name)
    else:
        assert caller_name is None
        assert host is None

    if ns is None:
        raise RuntimeError("Failed to locate Pyro name "
                           "server on the network!")

    cumulative_sleep_time = 0.0
    dispatchers = []
    for i in xrange(0,num_dispatcher_tries):
        ns_entries = None
        if using_pyro3:
            for (name,uri) in ns.flatlist():
                if name.startswith(":PyUtilibServer.dispatcher."):
                    if (name,uri) not in dispatchers:
                        dispatchers.append((name, uri))
        elif using_pyro4:
            for name in ns.list(prefix=":PyUtilibServer.dispatcher."):
                uri = ns.lookup(name)
                if (name,uri) not in dispatchers:
                    dispatchers.append((name, uri))
        if len(dispatchers) >= min_dispatchers:
            break
    return dispatchers

#
# a utility for shutting down Pyro-related components, which at the
# moment is restricted to the name server and any dispatchers. the
# mip servers will come down once their dispatcher is shut down.
# NOTE: this is a utility that should eventually become part of
#       pyutilib.pyro, but because is prototype, I'm keeping it
#       here for now.
#

def shutdown_pyro_components(host=None, num_retries=30):

    if _pyro is None:
        raise ImportError("Pyro or Pyro4 is not available")

    ns = get_nameserver(host=host, num_retries=num_retries)
    if ns is None:
        print("***WARNING - Could not locate name server "
              "- Pyro components will not be shut down")
        return

    if using_pyro3:
        ns_entries = ns.flatlist()
        for (name,uri) in ns_entries:
            if name.startswith(":PyUtilibServer.dispatcher."):
                try:
                    proxy = _pyro.core.getProxyForURI(uri)
                    proxy.shutdown()
                except:
                    pass
        for (name,uri) in ns_entries:
            if name == ":Pyro.NameServer":
                try:
                    proxy = _pyro.core.getProxyForURI(uri)
                    proxy._shutdown()
                    proxy._release()
                except:
                    pass
    elif using_pyro4:
        for name in ns.list(prefix=":PyUtilibServer.dispatcher."):
            try:
                uri = ns.lookup(name)
                proxy = _pyro.Proxy(uri)
                proxy.shutdown()
                proxy._pyroRelease()
                ns.remove(name)
            except:
                pass
        print("")
        print("*** NameServer must be shutdown manually when using Pyro4 ***")
        print("")

def set_maxconnections(max_connections=None):

    #
    # **NOTE: We add 1 to this setting so that it corresponds to the
    #         number of workers that can be connected. This makes
    #         more sense from a user perspective. If this is not done,
    #         setting max connections to something like 1, will not
    #         allow any workers to connect.
    #
    if max_connections is None:
        max_pyro_connections_envname = "PYUTILIB_PYRO_MAXCONNECTIONS"
        if max_pyro_connections_envname in os.environ:
            new_val = int(os.environ[max_pyro_connections_envname])
            print("Setting maximum number of connections to dispatcher to "
                  +str(new_val)+", based on specification provided by "
                  +max_pyro_connections_envname+" environment variable")
            if using_pyro3:
                _pyro.config.PYRO_MAXCONNECTIONS = new_val + 1
            else:
                _pyro.config.THREADPOOL_SIZE = new_val
    else:
        print("Setting maximum number of connections to dispatcher to "
              +str(max_connections)+", based on dispatcher max_connections keyword")
        if using_pyro3:
            _pyro.config.PYRO_MAXCONNECTIONS = max_connections + 1
        else:
            _pyro.config.THREADPOOL_SIZE = max_connections
