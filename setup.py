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

from codecs import open
import os
import re
from setuptools import setup

def get_version():
    pathname = os.path.join(os.path.dirname(__file__), 'gcsannex.py')
    with open(pathname, encoding='utf-8') as fh:
        match = re.search('^__version__ = [\'"]([0-9.]+)[\'"]$', fh.read(),
                re.MULTILINE)
        if match:
            return match.group(1)
        else:
            raise RuntimeError("Couldn't read version string")


def get_long_desc():
    pathname = os.path.join(os.path.dirname(__file__), 'README.rst')
    with open(pathname, encoding='utf-8') as fh:
        return fh.read()


setup(
    name='gcsannex',
    version=get_version(),
    description='git-annex external special remote for Google Cloud Storage',
    long_description=get_long_desc(),
    url='https://github.com/bgilbert/gcsannex',
    author='Benjamin Gilbert',
    author_email='bgilbert@backtick.net',
    license='GPLv3+',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Plugins',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Topic :: System :: Archiving',
    ],
    keywords='git-annex gcs Google Cloud Storage',
    install_requires=[
        'google-api-python-client',
        'PyCrypto',
    ],
    py_modules=[
        'gcsannex',
    ],
    entry_points={
        'console_scripts': [
            'git-annex-remote-gcs = gcsannex:main',
        ],
    },
)
