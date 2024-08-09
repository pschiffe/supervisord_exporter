#!/usr/bin/env python3

import argparse
import logging
import os
from xmlrpc.client import ServerProxy
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST


# Command line arguments
parser = argparse.ArgumentParser(description='Supervisor Exporter')
parser.add_argument('--supervisord-url', default='http://localhost:9001/RPC2', help='Supervisord XML-RPC URL')
parser.add_argument('--listen-address', default=':9101', help='Address to listen for HTTP requests')
parser.add_argument('--metrics-path', default='/metrics', help='Path under which to expose metrics')
parser.add_argument('--version', action='store_true', help='Displays application version')
args = parser.parse_args()

# SUPERVISORD_EXPORTER_SUPERVISORD_URL can override --supervisord-url
if os.environ.get('SUPERVISORD_EXPORTER_SUPERVISORD_URL'):
    args.supervisord_url = os.environ.get('SUPERVISORD_EXPORTER_SUPERVISORD_URL')

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics definition
supervisord_up = Gauge('supervisord_up', 'Supervisord XML-RPC connection status (1 if up, 0 if down)')
supervisor_processes_per_state = Gauge('supervisor_processes_per_state', 'Supervisor processes per state', ['state'])

supervisor_process_states = {
    'RUNNING': [10, 20, 40],
    'STOPPED': [0],
    'BACKOFF': [30],
    'EXITED': [100],
    'FATAL': [200],
    'UNKNOWN': [1000],
}

# Fetch Supervisor process info
def fetch_supervisor_process_info(supervisord_url):
    try:
        proxy = ServerProxy(supervisord_url)
        result = proxy.supervisor.getAllProcessInfo()
        #print(result)
        #logger.debug(f"Supervisor process info: {result}")
        supervisord_up.set(1)

        # Create a map to store the latest process information for each unique combination of name and group
        latest_info = {}

        for data in result:
            name = data['name']
            group = data['group']

            # Generate a unique key for the combination of name and group
            key = name + group

            # Check if the latest information for this combination already exists
            if key in latest_info:
                existing_start_time = latest_info[key]['start']
                new_start_time = data['start']

                # If the new information is more recent, update the latest_info map
                if new_start_time > existing_start_time:
                    latest_info[key] = data
            else:
                # If no previous information exists for this combination, add it to the map
                latest_info[key] = data

        # Clear the previous metric values
        supervisor_processes_per_state._metrics = {}

        # Count the number of processes in each state
        for state, codes in supervisor_process_states.items():
            for data in latest_info.values():
                if data['state'] in codes:
                    supervisor_processes_per_state.labels(state=state).inc()

    except Exception as e:
        logger.error(f"Error fetching Supervisor process info: {e}")
        supervisord_up.set(0)
        supervisor_processes_per_state._metrics = {}

# HTTP request handler
class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == args.metrics_path:
            fetch_supervisor_process_info(args.supervisord_url)
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_LATEST)
            self.end_headers()
            data = generate_latest()
            if isinstance(data, str):
                data = data.encode()
            self.wfile.write(data)
        else:
            self.send_error(404, 'Not Found')
    def log_message(self, format, *args):
        return

# Main function
def main():
    if args.version:
        print("Supervisor Exporter v0.1")
        return

    try:
        # Start HTTP server
        with HTTPServer((args.listen_address.split(':')[0], int(args.listen_address.split(':')[1])), RequestHandler) as server:
            logger.info(f"Listening on {args.listen_address}")
            server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
