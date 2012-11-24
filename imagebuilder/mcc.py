#!/usr/bin/python
#
# Copyright 2012 Michael K Johnson
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

# stores copies of modelcache files by the hash of the system model
# used to create them.  Especially useful for caching dependency
# resolution results

import hashlib
import os
import shutil

class ModelCacheCache(object):
    def __init__(self, directory, modeltext, targetroot):
        self.dir = directory
        self.targetfile = targetroot + '/var/lib/conarydb/modelcache'
        self.hash = hashlib.sha1(modeltext).hexdigest()
        self.hashfile = '/'.join((self.dir, self.hash))

    def prime(self):
        if os.path.exists(self.hashfile):
            targetdir = os.path.dirname(self.targetfile)
            if not os.path.exists(targetdir):
                os.makedirs(targetdir)
            shutil.copy(self.hashfile, self.targetfile)

    def store(self):
        if not os.path.exists(self.hashfile):
            if not os.path.exists(self.dir):
                os.makedirs(self.dir)
            shutil.copy(self.targetfile, self.hashfile)
