#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NetRC client

Compatibility:
    - Linux/Mac
    - Python 2.7.x
"""

# stdlib imports
import os
import logging
import netrc


# Define logger
logging.basicConfig(level=logging.CRITICAL)
log = logging.getLogger(__file__)


# Home directory
HOME = os.path.expanduser("~")
NETRC_FILE_PATH = os.path.abspath(os.path.join(HOME, ".netrc"))


class NetRc(object):
    """
    Read, write and update netrc file
    """

    def __init__(self, machine, login="", password="",
                 account=""):
        self.machine = machine
        self.login = login
        self.password = password
        self.account = account

    def create_or_update(self, path=NETRC_FILE_PATH):
        """
        Update netrc, if does not exist create new netrc
        """
        # get netrc
        machines, macros = self.get(path=path)

        # update netrc
        machines = self.update(machines)

        # write netrc
        self.write({
            "machines": machines,
            "macros": macros
            }, path=NETRC_FILE_PATH)

    def write(self, content, path=""):
        """
        Write content to netrc file
        """

        try:
            with open(path, "w+") as file:
                # machine content
                for machine, auth in content["machines"].iteritems():
                    log.debug("Writing machine %s to %s", machine, path)

                    file.writelines("\n".join([
                        "machine {0}".format(machine),
                        "login {0}".format(auth[0]),
                        "password {0}\n".format(auth[2])
                        ]))

                    # netrc account field is optional
                    if auth[1]:
                        log.debug("Writing machine account %s to %s", auth[1], path)
                        file.writelines("\naccount {0}\n".format(auth[1]))

                # macro content
                for macro, commands in content["macros"].iteritems():
                    log.debug("Writing macro %s to %s", macro, path)

                    file.writelines("\nmacdef %s\n" % macro)
                    file.writelines(commands)

                # 0600 permissions are required for netrc
                # TODO: Fix this for windows
                os.chmod(path, 0600)
                log.debug("Changed %s permissions to 0600", path)
        except Exception, e:
            log.error(e)
            raise Exception(e)

    def update(self, machines):
        """
        Update netrc content
        """

        if self.machine.lower() in machines.keys():
            machines[self.machine] = (self.login, machines[self.machine][1], self.password)

            log.debug("Updated netrc machine %s with login %s", self.machine, self.login)
        else:
            machines[self.machine] = (self.login, None, self.password)

            log.debug("Added new netrc machine %s with login %s", self.machine, self.login)

        return machines

    def get(self, path=""):
        """
        Get netrc content
        """
        try:
            auth = netrc.netrc(path)
            log.debug("Read netrc from location %s", path)

            return auth.hosts, auth.macros
        except IOError:
            log.debug("%s file missing, will be created automatically", path)
            return dict(), dict()
        except Exception, e:
            message = "%s %s" % (path, e)
            log.error(message)
            raise Exception(message)
