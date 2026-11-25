import os
import subprocess

def deploy():
    os.chdir('dist')
    subprocess.run(['python', 'setup.py', 'install'])