#!/usr/bin/python
#
# Copyright 2013 Michael K Johnson
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

# wrapper around SYS_clone system call

import ctypes
import os
import sys

CLONE_VM = 0x00000100 # Set if VM shared between processes.
CLONE_FS = 0x00000200 # Set if fs info shared between processes.
CLONE_FILES = 0x00000400 # Set if open files shared between processes.
CLONE_SIGHAND = 0x00000800 # Set if signal handlers shared.
CLONE_PTRACE = 0x00002000 # Set if tracing continues on the child.
CLONE_VFORK = 0x00004000 # Set if the parent wants the child to wake it up on mm_release.
CLONE_PARENT = 0x00008000 # Set if we want to have the same parent as the cloner.
CLONE_THREAD = 0x00010000 # Set to add to same thread group.
CLONE_NEWNS = 0x00020000 # Set to create new namespace.
CLONE_SYSVSEM = 0x00040000 # Set to shared SVID SEM_UNDO semantics.
CLONE_SETTLS = 0x00080000 # Set TLS info.
# CLONE_PARENT_SETTID = 0x00100000 # Store TID in userlevel buffer before MM copy.
# CLONE_CHILD_CLEARTID = 0x00200000 # Register exit futex and memory location to clear.
CLONE_DETACHED = 0x00400000 # Create clone detached.
CLONE_UNTRACED = 0x00800000 # Set if the tracing process can't force CLONE_PTRACE on this clone.
# CLONE_CHILD_SETTID = 0x01000000 # Store TID in userlevel buffer in the child.
CLONE_NEWUTS = 0x04000000	# New utsname group.
CLONE_NEWIPC = 0x08000000	# New ipcs.
CLONE_NEWUSER = 0x10000000	# New user namespace.
CLONE_NEWPID = 0x20000000	# New pid namespace.
CLONE_NEWNET = 0x40000000	# New network namespace.
CLONE_IO = 0x80000000	# Clone I/O context.

# intended to raise an error early if current architecture not supported
hostbits = 64 if True in ['/lib64/' in x for x in sys.path] else 32
architecture = os.uname()[4]
SYS_clone = {
    ('x86_64', 64): 56,
    ('i686', 64): 56,
    ('i386', 64): 56,
    ('i686', 32): 120,
    ('i386', 32): 120,
}[(architecture, hostbits)]
SYS_getpid = {
    ('x86_64', 64): 39,
    ('i686', 64): 39,
    ('i386', 64): 39,
    ('i686', 32): 20,
    ('i386', 32): 20,
}[(architecture, hostbits)]

class LateBoundLibc(object):
    def __init__(self):
        self.libc = None

    def _bind(self):
        if self.libc is None:
            self.libc = ctypes.CDLL('libc.so.6')

    def syscall(self, *args):
        self._bind()
        return self.libc.syscall(*args)

libc = LateBoundLibc()

def clone(flags):
    # we do not support child stacks or thread IDs
    return libc.syscall(SYS_clone, ctypes.c_uint32(flags),
        ctypes.c_uint32(0), ctypes.c_uint32(0), ctypes.c_uint32(0))

def getpid():
    # C library caches getpid() and does not know we called SYS_clone
    return libc.syscall(SYS_getpid)
