import os
from shutil import rmtree

def create_dir(dirname):
    if not os.path.exists(dirname):
        os.mkdir(dirname)

def remove_dir(name):
    if os.path.isdir(name):
        rmtree(name)

def remove_file(name):
    if os.path.exists(name):
        os.remove(name)
