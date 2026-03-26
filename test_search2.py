import sys
import os
os.environ['CONFIG_PATH'] = '/app/data/config.json'
os.environ['CUDA_VISIBLE_DEVICES'] = '' # Force CPU
sys.path.append(os.path.abspath('server'))
from src.main import search_notes, get_embedding, remember
import sqlite3

def run():
    print("Testing search on CPU...")
    results = search_notes("cooking pasta")
    print("Search results:")
    for r in results:
        print(r)

run()
