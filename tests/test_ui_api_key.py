import pytest
from playwright.sync_api import sync_playwright, expect
import os
import subprocess
import time
import requests

DOCKER_COMPOSE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docker-compose.auth.yml'))

