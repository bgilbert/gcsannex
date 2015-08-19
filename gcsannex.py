#
# gcsannex - git-annex external special remote for Google Cloud Storage
#
# Copyright (C) 2015 Benjamin Gilbert
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from __future__ import division
import argparse
from functools import wraps
import inspect
import json
import logging
import os
import socket
import ssl
import sys
import time
import traceback

try:
    import googleapiclient.discovery
    import googleapiclient.errors
    import googleapiclient.http
    import httplib2
    from oauth2client.client import SignedJwtAssertionCredentials
    have_google_api = True
except ImportError:
    have_google_api = False


__version__ = '0.1'


class StdinClosedError(Exception):
    pass


class NoSettingError(KeyError):
    pass


def get_function_args(f):
    while hasattr(f, 'wrapped'):
        f = f.wrapped
    return inspect.getargspec(f).args


def relay_errors(cmd, argspecs=(), reraise=False):
    def decorator(f):
        @wraps(f)
        def wrapper(self, *args, **kwargs):
            try:
                return f(self, *args, **kwargs)
            except StdinClosedError:
                raise
            except Exception, e:
                for line in traceback.format_exc().splitlines():
                    self.debug(line)
                argv = [cmd]
                for spec in argspecs:
                    if spec is Exception:
                        argv.append(str(e))
                    else:
                        i = get_function_args(f).index(spec)
                        assert i > 0, 'Bad argspec'
                        argv.append(args[i - 1])
                self.send(*argv)
                if reraise:
                    raise
        wrapper.wrapped = f
        return wrapper
    return decorator


class BaseSpecialRemote(object):
    def __init__(self, input=sys.stdin, output=sys.stdout):
        self._input = input
        self._output = output

    @relay_errors('ERROR', [Exception], reraise=True)
    def run(self):
        self.send('VERSION', 1)
        self._selftest()
        while True:
            cmd, argstr = self._recv()
            method = getattr(self, cmd.upper().lstrip('_'), None)
            if method is not None:
                argv = self._splitargv(argstr,
                        len(get_function_args(method)) - 1)
                method(*argv)
            else:
                self.send('UNSUPPORTED-REQUEST')

    def send(self, cmd, *args):
        self._output.write(' '.join([cmd] + [str(arg) for arg in args]) + '\n')
        self._output.flush()

    def _recv(self):
        line = self._input.readline()
        if not line:
            raise StdinClosedError
        line = line.rstrip('\r\n')
        if ' ' in line:
            return line.split(' ', 1)
        else:
            return line, ''

    @classmethod
    def _splitargv(cls, argstr, argc):
        if argc > 0:
            argv = argstr.split(' ', argc - 1)
            if len(argv) < argc:
                raise ValueError('Wrong number of arguments')
            return argv
        else:
            if argstr:
                raise ValueError('Wrong number of arguments')
            return []

    def _selftest(self):
        pass

    def get(self, cmd, setting=None, default=None):
        if setting is not None:
            self.send(cmd, setting)
        else:
            self.send(cmd)
        response_cmd, argstr = self._recv()
        assert response_cmd.upper() == 'VALUE', 'Response not VALUE'
        if not argstr and default is None:
            raise NoSettingError('Missing setting: ' + setting)
        return argstr or default

    def getcreds(self, setting):
        self.send('GETCREDS', setting)
        response_cmd, argstr = self._recv()
        assert response_cmd.upper() == 'CREDS', 'Response not CREDS'
        argv = self._splitargv(argstr, 2)
        if not argv[0] or not argv[1]:
            raise NoSettingError('Missing credentials: ' + setting)
        return argv

    def geturls(self, key, prefix=''):
        self.send('GETURLS', key, prefix)
        urls = []
        while True:
            response_cmd, argstr = self._recv()
            assert response_cmd.upper() == 'VALUE', 'Response not VALUE'
            if argstr:
                urls.append(argstr)
            else:
                return urls

    def debug(self, *args):
        self.send('DEBUG', ' '.join(args))

    @relay_errors('TRANSFER-FAILURE', ['subcmd', 'key', Exception])
    def TRANSFER(self, subcmd, key, file):
        method = getattr(self, 'transfer_' + subcmd.upper(), None)
        if method is not None:
            method(key, file)
        else:
            raise ValueError('Unsupported TRANSFER subcommand')
        self.send('TRANSFER-SUCCESS', subcmd, key)

    def ERROR(self, message):
        raise ValueError('Received error from git-annex: ' + message)


class GCSSpecialRemote(BaseSpecialRemote):
    OAUTH_SCOPE = 'https://www.googleapis.com/auth/devstorage.read_write'
    PUBLIC_URL_FORMAT = 'https://storage-download.googleapis.com/{bucket}/{object}'
    COST = 200  # expensiveRemoteCost
    CHUNK_SIZE = 1 << 20
    TIMEOUT = 30  # seconds
    RETRIES = 10

    def __init__(self, *args, **kwargs):
        BaseSpecialRemote.__init__(self, *args, **kwargs)
        self._uuid = None
        self._project = None
        self._location = None
        self._storageclass = None
        self._bucket = None
        self._public = None
        self._fileprefix = None
        self._service = None

    def _selftest(self):
        if not have_google_api:
            raise ImportError('Google Cloud client library not found')

    def _init(self):
        if self._uuid is not None:
            return
        self._uuid = self.get('GETUUID')
        self._project = self.get('GETCONFIG', 'project')
        self._location = self.get('GETCONFIG', 'location', 'US')
        self._storageclass = self.get('GETCONFIG', 'storageclass', 'STANDARD')
        name = self.get('GETCONFIG', 'name')
        self._bucket = self.get('GETCONFIG', 'bucket', name + '-' + self._uuid)
        self._public = self.get('GETCONFIG', 'public', '').lower() == 'yes'
        self._fileprefix = self.get('GETCONFIG', 'fileprefix', '')

    @property
    def _acl(self):
        # Replicate projectPrivate ACL, possibly add in publicRead
        acl = [
            {
                'entity': 'project-owners-' + self._project,
                'role': 'OWNER',
            }, {
                'entity': 'project-editors-' + self._project,
                'role': 'OWNER',
            }, {
                'entity': 'project-viewers-' + self._project,
                'role': 'READER',
            },
        ]
        if self._public:
            acl.append({
                'entity': 'allUsers',
                'role': 'READER',
            })
        return acl

    @property
    def _creds_setting(self):
        assert self._uuid is not None, 'Not initialized'
        return self._uuid + '-creds-v1'

    def _authenticate(self):
        email, escaped_private_key = self.getcreds(self._creds_setting)
        credentials = SignedJwtAssertionCredentials(email,
                escaped_private_key.replace('*', '\n'), self.OAUTH_SCOPE)
        http = httplib2.Http(timeout=self.TIMEOUT)
        self._service = googleapiclient.discovery.build('storage', 'v1',
                http=http, credentials=credentials)

    @relay_errors('INITREMOTE-FAILURE', [Exception])
    def INITREMOTE(self):
        self._init()

        creds_file = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if creds_file:
            with open(creds_file) as fh:
                creds = json.load(fh)
            email = creds['client_email']
            private_key = creds['private_key']
            # Mangle newlines for credential storage
            assert '*' not in private_key, 'Private key contains splats'
            self.send('SETCREDS', self._creds_setting, email,
                    '*'.join(private_key.splitlines()))

        try:
            self._authenticate()
        except NoSettingError:
            raise ValueError('No stored credentials and ' +
                    'GOOGLE_APPLICATION_CREDENTIALS not set')

        try:
            self._service.buckets().insert(
                project=self._project,
                predefinedAcl='projectPrivate',
                predefinedDefaultObjectAcl='projectPrivate',
                body=dict(
                    name=self._bucket,
                    location=self._location,
                    storageClass=self._storageclass,
                ),
            ).execute(num_retries=self.RETRIES)
        except googleapiclient.errors.HttpError, e:
            if e.resp.status == 409:
                # Bucket already exists, or some other conflict.
                # Ensure we have access to the bucket and that its
                # configuration matches our settings.
                metadata = self._service.buckets().get(
                    bucket=self._bucket,
                ).execute(num_retries=self.RETRIES)
                if self._location != metadata['location']:
                    raise ValueError('Bucket location "' +
                            metadata['location'] + '" cannot be changed')
                if self._storageclass != metadata['storageClass']:
                    raise ValueError('Bucket storage class "' +
                            metadata['storageClass'] + '" cannot be changed')
            else:
                raise

        self.send('INITREMOTE-SUCCESS')

    @relay_errors('PREPARE-FAILURE', [Exception])
    def PREPARE(self):
        self._init()
        self._authenticate()
        self.send('PREPARE-SUCCESS')

    def _object_name(self, key):
        return self._fileprefix + key

    def _object_url(self, key):
        return self.PUBLIC_URL_FORMAT.format(bucket=self._bucket,
                object=self._object_name(key))

    def _retry_timeout(self, fn):
        for i in range(self.RETRIES + 1):
            try:
                return fn()
            except (socket.timeout, ssl.SSLError), e:
                # Timeouts under SSL look like SSLErrors, but not all
                # SSLErrors are timeouts.  Retry, a finite number of times,
                # with backoff.
                if i < self.RETRIES:
                    backoff = min(2 ** i, self.TIMEOUT // 2)
                    self.debug('{}, retrying in {} seconds'.format(e, backoff))
                    time.sleep(backoff)
                else:
                    raise

    def transfer_STORE(self, key, file):
        assert self._service is not None, 'Not authenticated'
        media = googleapiclient.http.MediaFileUpload(
            file,
            mimetype='application/octet-stream',
            chunksize=self.CHUNK_SIZE,
            resumable=True,
        )
        req = self._service.objects().insert(
            bucket=self._bucket,
            name=self._object_name(key),
            body=dict(
                acl=self._acl,
            ),
            media_body=media,
        )

        resp = None
        last_progress = 0
        total_size = os.stat(file).st_size
        while resp is None:
            status, resp = self._retry_timeout(
                    lambda: req.next_chunk(num_retries=self.RETRIES))
            if status:
                progress = status.progress()
                if progress - last_progress >= 0.01:
                    self.send('PROGRESS', int(progress * total_size))
                    last_progress = progress

        if self._public:
            self.send('SETURLPRESENT', key, self._object_url(key))

    def transfer_RETRIEVE(self, key, file):
        assert self._service is not None, 'Not authenticated'
        metadata = self._service.objects().get(
            bucket=self._bucket,
            object=self._object_name(key),
            fields='name,size',
        ).execute(num_retries=self.RETRIES)
        total_size = int(metadata['size'])

        req = self._service.objects().get_media(
            bucket=self._bucket,
            object=self._object_name(key),
        )
        with open(file, 'w') as fh:
            downloader = googleapiclient.http.MediaIoBaseDownload(fh, req,
                    chunksize=self.CHUNK_SIZE)
            done = False
            last_progress = 0
            while not done:
                status, done = self._retry_timeout(
                        lambda: downloader.next_chunk(num_retries=self.RETRIES))
                if status:
                    progress = status.progress()
                    if progress - last_progress >= 0.01:
                        self.send('PROGRESS', int(progress * total_size))
                        last_progress = progress

    @relay_errors('CHECKPRESENT-UNKNOWN', ['key', Exception])
    def CHECKPRESENT(self, key):
        assert self._service is not None, 'Not authenticated'
        try:
            self._service.objects().get(
                bucket=self._bucket,
                object=self._object_name(key),
                fields='name',
            ).execute(num_retries=self.RETRIES)
            self.send('CHECKPRESENT-SUCCESS', key)
        except googleapiclient.errors.HttpError, e:
            if e.resp.status == 404:
                self.send('SETURLMISSING', key, self._object_url(key))
                self.send('CHECKPRESENT-FAILURE', key)
            else:
                raise

    @relay_errors('REMOVE-FAILURE', ['key', Exception])
    def REMOVE(self, key):
        assert self._service is not None, 'Not authenticated'
        try:
            self._service.objects().delete(
                bucket=self._bucket,
                object=self._object_name(key),
            ).execute(num_retries=self.RETRIES)
        except googleapiclient.errors.HttpError, e:
            if e.resp.status != 404:
                raise
        self.send('SETURLMISSING', key, self._object_url(key))
        self.send('REMOVE-SUCCESS', key)

    def GETCOST(self):
        self.send('COST', self.COST)


class SpecialRemoteDebugLogHandler(logging.Handler):
    def __init__(self, remote):
        logging.Handler.__init__(self)
        self._remote = remote

    def emit(self, record):
        self._remote.debug(self.format(record))


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--version', action='version',
            version='gcsannex ' + __version__)
    parser.parse_args()

    remote = GCSSpecialRemote()
    # Redirect logging to git-annex debug stream.  This is necessary
    # because googleapiclient.http logs retried requests to the root logger
    # at WARNING level, which would otherwise go to stderr.
    logging.getLogger().addHandler(SpecialRemoteDebugLogHandler(remote))
    try:
        remote.run()
    except StdinClosedError:
        pass
    except Exception:
        sys.exit(1)
