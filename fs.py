import os
import shutil

def create_dir(dirname):
    if not os.path.exists(dirname):
        os.mkdir(dirname)

def remove_dir(name):
    if os.path.isdir(name):
        shutil.rmtree(name)

def remove_file(name):
    if os.path.exists(name):
        os.remove(name)

def move_file(old_path, new_path):
    if os.path.exists(old_path):
        shutil.move(old_path, new_path)