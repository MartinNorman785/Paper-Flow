import os
import pickle

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def save_blocks(blocks, filename):
    cache_file = os.path.join(CACHE_DIR, filename + ".pkl")
    with open(cache_file, "wb") as f:
        pickle.dump(blocks, f)

def load_blocks(filename):
    cache_file = os.path.join(CACHE_DIR, filename + ".pkl")
    if os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            return pickle.load(f)
    return None