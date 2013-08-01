import traceback
from collections import defaultdict
from itertools import imap
import requests
from django.core.management.base import BaseCommand, CommandError
from ceph.models import Cluster as ClusterModel
from ceph.models import PGPoolDump, ClusterStatus

class CephRestClient(object):
    """
    Wrapper around the Ceph RESTful API.
    """
    def __init__(self, url):
        self.__url = url
        if self.__url[-1] != '/':
            self.__url += '/'

    def _query(self, endpoint):
        "Interrogate a Ceph API endpoint"
        hdr = {'accept': 'application/json'}
        r = requests.get(self.__url + endpoint, headers = hdr)
        return r.json()

    def get_space_stats(self):
        "Get the raw `ceph df` output"
        return self._query("df")["output"]

    def get_health(self):
        "Get the raw `ceph health detail` output"
        return self._query("health?detail")["output"]

    def get_osds(self):
        "Get the raw `ceph osd dump` output"
        return self._query("osd/dump")["output"]

    def get_pg_pools(self):
        "Get the raw `ceph pg/dump?dumpcontents=pools` output"
        return self._query("pg/dump?dumpcontents=pools")["output"]

class ModelAdapter(object):
    def __init__(self, client, cluster):
        self.client = client
        self.cluster = cluster

    def refresh(self):
        "Call each _populate* method, then save the model instance"
        attrs = filter(lambda a: a.startswith('_populate_'), dir(self))
        for attr in attrs:
            getattr(self, attr)()
        self.cluster.save()

    def _populate_space(self):
        "Fill in the cluster space statistics"
        data = self.client.get_space_stats()['stats']
        self.cluster.space = {
            'used_bytes': data['total_used'] * 1024,
            'capacity_bytes': data['total_space'] * 1024,
            'free_bytes': data['total_avail'] * 1024,
        }

    def _populate_health(self):
        "Fill in the cluster health state"
        data = self.client.get_health()
        self.cluster.health = {
            'overall_status': data['overall_status'],
            'detail': data['detail'],
            'summary': data['summary'],
        }

    def _populate_osds(self):
        "Fill in the set of cluster OSDs"
        data = self.client.get_osds()
        self.cluster.osds = data["osds"]

    def _populate_counters(self):
        self.cluster.counters = {
            'pool': self._calculate_pool_counters(),
        }

    def _calculate_pool_counters(self):
        fields = ['num_objects_unfound', 'num_objects_missing_on_primary',
            'num_deep_scrub_errors', 'num_shallow_scrub_errors',
            'num_scrub_errors', 'num_objects_degraded']
        counts = defaultdict(lambda: 0)
        pools = self.client.get_pg_pools()
        for pool in imap(lambda p: p['stat_sum'], pools):
            for key, value in pool.items():
                counts[key] += min(value, 1)
        for delkey in set(counts.keys()) - set(fields):
            del counts[delkey]
        counts['total'] = len(pools)
        return counts

class Command(BaseCommand):
    """
    Administrative function for refreshing Ceph cluster stats.

    The `ceph_refresh` command will attempt to update statistics for each
    registered cluster found in the database.

    A failure that occurs while updating cluster statistics will abort the
    refresh for that cluster. An attempt will be made for other clusters.
    """
    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        self._last_response = None    # last cluster query response

    def handle(self, *args, **options):
        """
        Update statistics for each registered cluster.
        """
        clusters = ClusterModel.objects.all()
        self.stdout.write("Updating %d clusters..." % (len(clusters),))
        for cluster in clusters:
            client = CephRestClient(cluster.api_base_url)
            adapter = ModelAdapter(client, cluster)
            adapter.refresh()
            self.stdout.write("Refreshing data from cluster: %s (%s)" % \
                    (cluster.name, cluster.api_base_url))
            try:
                self._refresh_cluster_status(cluster)
            except Exception as e:
                # dump context from the last cluster query response
                self._print_response(self.stderr, self._last_response)
                self.stderr.write(traceback.format_exc())
        self.stdout.write("Update completed!")

    def _print_response(self, out, r):
        """
        Print out requests.py Response object information.
        """
        if not r:
            out.write("last response: <not set>")
            return
        out.write("last response: status code: %d" % (r.status_code,))
        out.write("last response: headers: %s" % (r.headers,))
        out.write("last response: content: %s" % (r.text,))

    def _cluster_query(self, cluster, url):
        """
        Fetch a JSON result for a Ceph REST API target.
        """
        url_base = cluster.api_base_url
        if url_base[-1] != '/':
            url_base.append('/')
        hdr = {'accept': 'application/json'}
        r = requests.get(url_base + url, headers = hdr)
        self._last_response = r
        return r.json()

    def _refresh_cluster_status(self, cluster):
        """
        Update cluster status.
        """
        result = self._cluster_query(cluster, "status")
        ClusterStatus(cluster=cluster, report=result['output']).save()
        self.stdout.write("(%s): updated cluster status" % (cluster.name,))
