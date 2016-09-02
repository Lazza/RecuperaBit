# File to be used with Python For Android
# https://github.com/kuri65536/python-for-android/
#
# - Install the required APKs
# - Put this file in the root sl4a directory
# - Add the RecuperaBit directory in the root sl4a directory
# - Save your dd image as /sdcard/image.dd
# - Run the script
# - Wait... quite a bit :D

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from RecuperaBit.main import main

sys.argv.append('/sdcard/image.dd')
sys.argv.append('-o')
sys.argv.append('/sdcard/recuperabit_output')

main()
