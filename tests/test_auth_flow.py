import pytest
import subprocess
import time
import requests
import os
import json

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.auth.yml'))

