# encoding: utf-8
from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import os
from os import O_CREAT
import stat
import time

from paramiko import ServerInterface, AUTH_SUCCESSFUL, OPEN_SUCCEEDED
from paramiko.sftp import SFTP_OK, SFTP_NO_SUCH_FILE, SFTP_FAILURE, SFTP_OP_UNSUPPORTED
from paramiko.sftp_attr import SFTPAttributes
from paramiko.sftp_handle import SFTPHandle
from paramiko.sftp_si import SFTPServerInterface

from pytest_sftpserver.sftp.util import abspath


class VirtualSFTPHandle(SFTPHandle):
    def __init__(self, path, content_provider, flags=0, attr=None):
        super(VirtualSFTPHandle, self).__init__()
        self.path = path
        self.content_provider = content_provider
        if (self.content_provider.get(self.path, atime_change=False) is None
                and flags and flags & O_CREAT == O_CREAT):
            if attr is not None:
                times = [getattr(attr, 'st_atime', None),
                         getattr(attr, 'st_mtime', None)]
            else:
                times = None
            # Create new empty "file"
            self.content_provider.put(path, "", times)

    def close(self):
        return SFTP_OK

    def chattr(self, attr):
        if self.content_provider.get(self.path, atime_change=False) is None:
            return SFTP_NO_SUCH_FILE
        if hasattr(attr, 'st_atime') or hasattr(attr, 'st_mtime'):
            times = self.content_provider.get_times(self.path)
            # Mutates the stored times list in-place
            times[0] = getattr(attr, 'st_atime', times[0])
            times[1] = getattr(attr, 'st_mtime', times[1])
        return SFTP_OK

    def write(self, offset, data):
        if offset != 0:
            return SFTP_OP_UNSUPPORTED
        return SFTP_OK if self.content_provider.put(self.path, data) else SFTP_NO_SUCH_FILE

    def read(self, offset, length):
        if self.content_provider.get(self.path, atime_change=False) is None:
            return SFTP_NO_SUCH_FILE

        return str(self.content_provider.get(self.path))[offset:offset + length]

    def stat(self):
        if self.content_provider.get(self.path, atime_change=False) is None:
            return SFTP_NO_SUCH_FILE

        #mtime = calendar.timegm(datetime.now().timetuple())

        sftp_attrs = SFTPAttributes()
        sftp_attrs.st_size = self.content_provider.get_size(self.path)
        sftp_attrs.st_uid = 0
        sftp_attrs.st_gid = 0
        sftp_attrs.st_mode = (
            stat.S_IRWXO |
            stat.S_IRWXG |
            stat.S_IRWXU |
            (
                stat.S_IFDIR
                if self.content_provider.is_dir(self.path)
                else stat.S_IFREG
            )
        )
        (sftp_attrs.st_atime,
            sftp_attrs.st_mtime) = self.content_provider.get_times(self.path)
        sftp_attrs.filename = os.path.basename(self.path)
        return sftp_attrs


class VirtualSFTPServerInterface(SFTPServerInterface):
    def __init__(self, server, *largs, **kwargs):
        self.content_provider = kwargs.pop('content_provider', None)
        ":type: ContentProvider"
        super(VirtualSFTPServerInterface, self).__init__(server, *largs, **kwargs)

    @abspath
    def list_folder(self, path):
        return [
            self.stat(os.path.join(path, fname))
            for fname
            in self.content_provider.list(path)
        ]

    @abspath
    def open(self, path, flags, attr):
        return VirtualSFTPHandle(path, self.content_provider, flags=flags,
                                 attr=attr)

    @abspath
    def remove(self, path):
        return SFTP_OK if self.content_provider.remove(path) else SFTP_NO_SUCH_FILE

    @abspath
    def rename(self, oldpath, newpath):
        content = self.content_provider.get(oldpath, atime_change=False)
        if not content:
            return SFTP_NO_SUCH_FILE
        oldtimes = self.content_provider.get_times(oldpath)
        res = self.content_provider.put(newpath, content, oldtimes)
        if res:
            res = res and self.content_provider.remove(oldpath)
        return SFTP_OK if res else SFTP_FAILURE

    @abspath
    def rmdir(self, path):
        return SFTP_OK if self.content_provider.remove(path) else SFTP_FAILURE

    @abspath
    def mkdir(self, path, attr):
        if self.content_provider.get(path, atime_change=False) is not None:
            return SFTP_FAILURE
        times = [getattr(attr, 'st_atime', None),
                 getattr(attr, 'st_mtime', None)]
        return (SFTP_OK if self.content_provider.put(path, {}, times)
                else SFTP_FAILURE)

    @abspath
    def stat(self, path):
        return VirtualSFTPHandle(path, self.content_provider).stat()

    @abspath
    def chattr(self, path, attr):
        return VirtualSFTPHandle(path, self.content_provider).chattr(attr)


class AllowAllAuthHandler(ServerInterface):
    def check_auth_none(self, username):
        return AUTH_SUCCESSFUL

    def check_auth_password(self, username, password):
        return AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        return AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return OPEN_SUCCEEDED
