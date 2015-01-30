import argparse
from contextlib import contextmanager
import json
import logging
import os
import sys
import subprocess

# The log is very verbose by default, filtered at handler level
log = logging.getLogger('calamari_osd_location')
log.setLevel(logging.DEBUG)

def main():
    parser = argparse.ArgumentParser(description="""
Calamari setup tool.
    """)

    parser.add_argument('--cluster',
                        dest="cluster",
                        action='store_true',
                        default=False,
                        help="ceph cluster to operate on",
                        required=False)
    parser.add_argument('--id',
                        dest="id",
                        action='store_true',
                        default=False,
                        help="id to emit crush location for")
    parser.add_argument('--type',
                        dest="type",
                        action='store_true',
                        default=False,
                        help="<osd|mds|client>")


    args = parser.parse_args()

    print 'host={host} root=default'.format(host='vpm006')
