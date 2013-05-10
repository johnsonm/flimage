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

import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from plumbum import FG, BG, local
from plumbum.cmd import bootman, chroot, conary, cp
from plumbum.cmd import dd, depmod, dmsetup, dracut
from plumbum.cmd import extlinux, kpartx, losetup, mount
from plumbum.cmd import parted, sgdisk, sh, tar, umount
from plumbum.cmd import echo, sqlite3
import plumbum.version

from imagebuilder import clone

# use the parted codes for partition types
DOS = 'msdos'
GPT = 'gpt'

class ImageBuilderError(IOError):
    pass

class ImageBuilder(object):

    def __init__(self, basedir, size, rootdev, fstype, partType=DOS, inspectFailure=False):
        self.basedir = basedir
        self.size = size
        self.rootdev = rootdev
        self.fstype = fstype
        self.partType = partType
        self.inspectFailure = inspectFailure
        self.errfd, self.errname = tempfile.mkstemp(prefix='mke.',
                                                    suffix='.log',
                                                    dir=basedir)
        fd, self.image = tempfile.mkstemp(prefix='mki.',
                                          suffix='.img',
                                          dir=basedir)
        self.mountDevice = self.image
        self.loopDevices = []
        self.conaryDbMounted = False
        os.close(fd)
        self.rootdir = None

    def removeRootdir(self):
        if self.rootdir is not None:
            os.rmdir(self.rootdir)

    def cleanUp(self):
        if self.inspectFailure:
            # give the user a chance to investigate the problem first
            self.rootShell()
        for cleanup in (self.unmountConarydb,
                        self.unmountFilesystems,
                        self.unmountFilesystem,
                        self.unloopImage,
                        self.removeRootdir):
            try:
                cleanup()
            except:
                pass

    def raiseError(self, message):
        sys.stderr.write('See errors in %s (last 10 lines follow):\n')
        sys.stderr.write(''.join(file(self.errname).readlines()[-10:]))
        raise ImageBuilderError, message

    def clone(self, cmd):
        retcode = 0

        pid = clone.clone(signal.SIGCHLD|clone.CLONE_NEWPID)
        if pid < 0:
            self.raiseError('clone failed')

        if pid == 0:
            pid = clone.getpid()
            if pid != 1:
                os.write(self.errfd, 'CONTAINER FAILED: pid %d !== 1\n' %(pid))
                os._exit(retcode)

            try:
                os.write(self.errfd, 'CONTAINED COMMAND: "%s"\n' % (str(cmd)))
                sys.stdout.write(str(cmd) + '\n')
                sys.stdout.flush()
                cmd(stdout=None, stderr=self.errfd)
            except:
                os.write(self.errfd, 'ERROR exit code from contained command\n')
                retcode = 1
            finally:
                os.write(self.errfd, '%d SIGTERM\n' % (clone.getpid()))
                try:
                    os.kill(-1, signal.SIGTERM)
                except OSError:
                    # no processes to kill
                    os._exit(retcode)
                # kill succeeded, must have been children to kill.
                # Sleep long enough to give them time to clean up.
                time.sleep(2)
                # If the child processes do not die in reasonable time
                # from SIGTERM, kill them with SIGKILL.
                os.write(self.errfd, '%d sending SIGKILL...\n' % (clone.getpid()))
                try:
                    os.kill(-1, signal.SIGKILL)
                    os.write(self.errfd, 'some processes remained to SIGKILL\n')
                except:
                    # Yay, they cleaned up
                    os.write(self.errfd, 'all processes properly terminated\n')
                # as long as they are dead, the real init can reap them later
                os._exit(retcode)

        os.write(self.errfd, '%d WAITING for %d...\n' % (clone.getpid(), pid))
        pid, status = os.waitpid(pid, 0)
        os.write(self.errfd, '%d terminated with exit status %d\n' % (
            pid, os.WEXITSTATUS(status)))
        if not os.WIFEXITED(status):
            self.raiseError('container %d killed' %(pid))
        if os.WEXITSTATUS(status) != 0:
            self.raiseError('contained command failed')

    def run(self, cmd, fg=False):
        os.write(self.errfd, 'RUNNING COMMAND: "%s"\n' % str(cmd))
        sys.stdout.write(str(cmd) + '\n')
        sys.stdout.flush()
        if fg:
            result = cmd(stdout=None, stderr=self.errfd)
        else:
            result = cmd(stderr=self.errfd)
        return result

    def rootShell(self):
        # does not call run() to avoid adding an "interactive" mode to run()
        try:
            chroot[self.rootdir, 'sh'] & FG
        except:
            sys.stdout.write('failed to invoke shell in image' + '\n')
            sys.stdout.flush()

    def allocateImage(self, sparse=True):
        if sparse:
            self.run(dd['if=/dev/zero', 'of=%s'%self.image, 'bs=1M',
                'seek=%d' %(self.size), 'count=0', ])
        else:
            self.run(dd['if=/dev/zero', 'of=%s'%self.image, 'bs=1M',
                'count=%d' %self.size, ])

    def partitionImage(self, size):
        sectors = size * 2048
        firstsector = 2048 # use fdisk default of reserving 1MB
        if self.partType == DOS:
            lastsector = sectors - 1
        else:
            # at least 34 (1+1+32) sectors reserved for the header and
            # partition table copy at the end of the disk.  Leave room
            # for a full default 64K stride for now
            lastsector = sectors - 127
        self.run(parted['--script', self.image,
            'unit', 's',
            'mklabel', self.partType,
            'mkpart', 'primary', '%d'%firstsector, '%d'%lastsector,
            'set', '1', 'boot', 'on'])
        # extlinux requires the legacy_boot flag in GPT
        if self.partType == GPT:
            # parted should take set 1 legacy_boot on, but may be too old
            self.run(sgdisk[self.image, '--attributes=1:set:2'])

    def loopImage(self):
        lines = self.run(kpartx['-a', '-v', self.image]).split('\n')
        if lines:
            self.mountDevice = '/dev/mapper/%s' %(
                [x.split()[2] for x in lines if x][0])
            self.loopDevices.append(self.mountDevice)

    def createFilesystem(self):
        return self.run(local['mkfs.%s' %self.fstype]['-F', '-L', '/', self.mountDevice])

    def unloopImage(self):
        if self.loopDevices:
            self.run(kpartx['-d', self.image])
            # in case kpartx has failed for any reason, remove the mappings
            for device in self.loopDevices:
                if os.path.exists(device):
                    self.run(dmsetup['remove', device])
                # /dev/mapper/loop0p1 -> /dev/loop0
                base = device.replace('/mapper', '')[:-2]
                dev = os.path.basename(base)
                backing = '/sys/block/' + dev + '/loop/backing_file'
                if os.path.exists(backing):
                    self.run(losetup['-d', base])

    def mountFilesystem(self):
        self.rootdir = tempfile.mkdtemp(prefix='mkd.', dir=self.basedir)
        self.run(mount[self.mountDevice, '-o', 'barrier=0,data=writeback', '-t', self.fstype, self.rootdir])
        
    def unmountFilesystem(self):
        self.run(umount[self.rootdir])

    def prepareFilesystem(self, modelFile):
        os.mkdir(self.rootdir + '/dev', 0755)
        os.mknod(self.rootdir + '/dev/null',  0666|stat.S_IFCHR, os.makedev(1,3))
        os.mknod(self.rootdir + '/dev/zero',  0666|stat.S_IFCHR, os.makedev(1,5))
        os.mknod(self.rootdir + '/dev/full',  0666|stat.S_IFCHR, os.makedev(1,7))
        os.mknod(self.rootdir + '/dev/random',  0666|stat.S_IFCHR, os.makedev(1,8))
        os.mknod(self.rootdir + '/dev/urandom',  0666|stat.S_IFCHR, os.makedev(1,9))
        os.mknod(self.rootdir + '/dev/console',  0600|stat.S_IFCHR, os.makedev(5,1))

        os.mkdir(self.rootdir + '/dev/shm', 01777)
        os.mkdir(self.rootdir + '/dev/pts', 0755)
        os.mkdir(self.rootdir + '/tmp', 01777)
        os.mkdir(self.rootdir + '/etc', 0755)
        os.mkdir(self.rootdir + '/etc/conary', 0755)
        os.mkdir(self.rootdir + '/etc/sysconfig', 0755)
        os.mkdir(self.rootdir + '/proc', 0755)
        os.mkdir(self.rootdir + '/sys', 0755)
        os.mkdir(self.rootdir + '/var', 0755)
        os.mkdir(self.rootdir + '/var/tmp', 01777)
        os.mkdir(self.rootdir + '/var/lib', 0755)
        os.mkdir(self.rootdir + '/var/lib/conarydb', 0755)
        file(self.rootdir + '/etc/fstab', 'w+').write(
            'LABEL=/            /           ext4    defaults        1 1\n'
            'tmpfs              /tmp        tmpfs   defaults        0 0\n'
            'tmpfs              /dev/shm    tmpfs   defaults        0 0\n'
            'devpts             /dev/pts    devpts  gid=5,mode=620  0 0\n'
            'sysfs              /sys        sysfs   defaults        0 0\n'
            'proc               /proc       proc    defaults        0 0\n')
        file(self.rootdir + '/etc/mtab', 'w+').write('')
        if modelFile:
            file(self.rootdir + '/etc/conary/system-model', 'w+').write(
                file(modelFile).read())

        self.run(mount['proc', '-t', 'proc', self.rootdir + '/proc'])
        self.run(mount['devpts', '-t', 'devpts',
                      self.rootdir + '/dev/pts', '-o', 'gid=5,mode=620'])
        self.run(mount['sys', '-t', 'sysfs', self.rootdir + '/sys'])
        self.run(mount['tmpfs', '-t', 'tmpfs', self.rootdir + '/dev/shm'])
        self.run(mount['tmpfs', '-t', 'tmpfs', self.rootdir + '/tmp'])
        self.run(mount['tmpfs', '-t', 'tmpfs', self.rootdir + '/var/tmp'])
        # need to have the right permissions after mounting
        os.chmod(self.rootdir + '/dev/shm', 01777)
        os.chmod(self.rootdir + '/dev/pts', 0755)
        os.chmod(self.rootdir + '/tmp', 01777)

    def mountConarydb(self):
        # speed up database by not waiting for disk
        self.run(mount['tmpfs', '-t', 'tmpfs',
                        self.rootdir + '/var/lib/conarydb'])
        self.conaryDbMounted = True

    def tuneConarydb(self, pageSize=4096, defaultCacheSize=2000):
        self.run(echo['pragma default_cache_size=%d; '
                      'pragma page_size=%d; '
                      'vacuum;' % (defaultCacheSize, pageSize)]
                 | sqlite3[self.rootdir + '/var/lib/conarydb/conarydb'])

    def writePostConfig(self, timezone, lang, keytable):
        configFiles = [
            ('/etc/sysconfig/clock',
             ('ZONE="%s"' % (timezone),
              'UTC=true',
              '')),
            ('/etc/sysconfig/i18n', 
             ('LANG="%s"' % (lang),
              'SYSFONT="latarcyrheb-sun16"',
              '')),
            ('/etc/sysconfig/keyboard',
             ('KEYBOARDTYPE="pc"',
              'KEYTABLE="%s"' % (keytable),
              '')),
            ('/etc/sysconfig/mouse',
             ('MOUSETYPE="imps2"',
              'XEMU3="no" # yes = emulate 3 buttons',
              'XMOUSETYPE="imps2"',
              '# Common mouse types:',
              '# imps2 -- A generic USB wheel mouse',
              '# microsoft -- A microsoft mouse',
              '# logitech -- A logitech mouse',
              '# ps/2 -- Legacy PS/2 mouse',
              ''))
        ]
        for filename, contents in configFiles:
            f = self.rootdir + filename
            if not os.path.exists(f): # or in argument exclude list eventually
                file(f, 'w+').write('\n'.join(contents))

        tzFile = self.rootdir + '/usr/share/zoneinfo/' + timezone
        if os.path.exists(tzFile):
            # copy2 preserves metadata
            shutil.copy2(tzFile, self.rootdir + '/etc/localtime')
        else:
            self.raiseError('specified zoneinfo file %s missing' % tzFile)

    def finishFilesystem(self):
        mbr = None
        if self.partType == GPT:
            mbrPath = self.rootdir + '/boot/extlinux/gptmbr.bin'
        else:
            mbrPath = self.rootdir + '/boot/extlinux/mbr.bin'
        if os.path.exists(mbrPath):
            mbr = file(mbrPath).read()

            self.run(extlinux['-i', self.rootdir + '/boot/extlinux'])

        if self.conaryDbMounted:
            # copy conary database from tmpfs to image
            os.mkdir(self.rootdir + '/var/lib/conarydb.real', 0755)
            conarydbFiles = [self.rootdir + '/var/lib/conarydb/' + x
                             for x in os.listdir(self.rootdir
                                                 + '/var/lib/conarydb')]
            for conaryFile in conarydbFiles:
                self.run(cp['-a',
                                conaryFile,
                                self.rootdir + '/var/lib/conarydb.real/'])
            self.unmountConarydb()
            os.rename(self.rootdir + '/var/lib/conarydb.real',
                      self.rootdir + '/var/lib/conarydb')

        self.unmountFilesystems()

        if mbr:
            f = os.open(self.image, os.O_WRONLY)
            l = os.write(f, mbr)
            os.close(f)
            if l != len(mbr):
                self.raiseError('failed to write full MBR: wrote %d of %d bytes'
                                % (l, len(mbr)))

    def unmountConarydb(self):
        self.run(umount[self.rootdir + '/var/lib/conarydb'])

    def unmountFilesystems(self):
        self.run(umount[self.rootdir + '/proc'])
        self.run(umount[self.rootdir + '/dev/pts'])
        self.run(umount[self.rootdir + '/sys'])
        self.run(umount[self.rootdir + '/dev/shm'])
        self.run(umount[self.rootdir + '/var/tmp'])
        self.run(umount[self.rootdir + '/tmp'])

    def createTarball(self):
        fd, t = tempfile.mkstemp(prefix='image.',
                                 suffix='.tar.gz',
                                 dir=self.basedir)
        os.close(fd)
        self.run(tar['-C', self.rootdir, '-c', '-z', '-f', t, '.'])
        return t

    def installTarball(self, prefix, tarball):
        basedir = self.rootdir + prefix
        if not os.path.exists(basedir):
            os.makedirs(basedir, mode=0755)
        self.run(tar['-C', basedir, '-x', '-z', '-f', tarball])

    def installTarballWithPrefix(self, tarball):
        prefix = '/'
        if ':' in tarball:
            prefix, tarball = tarball.split(':', 1)
        self.installTarball(prefix, tarball)

    def installPreImage(self, pre_image):
        if pre_image:
            self.installTarballWithPrefix(pre_image)

    def installSystem(self):
        # Note that system config is applied; this is generally not
        # important but may cause :supdoc noise later on (for instance).
        # This can be improved later
        self.run(conary['sync',
             '--no-interactive',
             '--replace-unmanaged-files',
             '--tag-script=%s/tmp/tag-script' %self.rootdir,
             '--root', self.rootdir], fg=True)

    def removeRollbacks(self):
        # remove conary rollbacks to avoid rolling back to uninstalled
        self.run(conary['rmrollback', 'r.0',
             '--no-interactive',
             '--root', self.rootdir])

    def installPostImage(self, post_image):
        if post_image:
            self.installTarballWithPrefix(post_image)

    def createBootloaderConf(self):
        self.kver = os.listdir(self.rootdir + '/lib/modules')[0]
        file(self.rootdir + '/etc/bootloader.conf', 'w').write('\n'.join((
            'read_only',
            'timeout 50',
            'default %s' % self.kver,
            "include '/etc/bootloader.d/*'",
            "linux %s 'Linux %s' /boot/vmlinuz-%s /boot/initrd-%s" %((self.kver,) * 4),
            ''
        )))

    def convertPasswords(self):
        self.run(chroot[self.rootdir, 'pwconv'])

    def unsetRootPassword(self):
        if (not isinstance(plumbum.version, tuple)) or plumbum.version[0] < 1:
            self.raiseError('newer plumbum required to reset root password')
        self.run(chroot[self.rootdir, 'usermod', '-p', '', 'root'])

    def setInitlevel(self, initlevel):
        inittab = file(self.rootdir + '/etc/inittab').readlines()
        i = []
        for line in inittab:
            if line.startswith('id:') and 'initdefault' in line:
                i.append('id:%s:initdefault:\n' % initlevel)
            else:
                i.append(line)
        file(self.rootdir + '/etc/inittab', 'w').write(''.join(i))

    def runTagScripts(self):
        tags = file(self.rootdir + '/tmp/tag-script').read()
        tags = tags.replace('/sbin/ldconfig\n', '')
        tags = '/sbin/ldconfig\n' + tags
        tags = tags.split('\n')
        t = []
        ignore = False
        for tagline in tags:
            if tagline.startswith('/usr/libexec/conary/tags/kernel files update '):
                ignore = True
            if tagline.startswith('/usr/libexec/conary/tags/extlinux files update '):
                ignore = True
            if tagline.startswith('/usr/libexec/conary/tags/udev files update '):
                ignore = True
            if ignore:
                if tagline == 'EOF':
                    ignore = False
            else:
                t.append(tagline)
        t.append('')
        tags = '\n'.join(t)
        file(self.rootdir + '/tmp/tag-script', 'w').write(tags)
        self.clone(chroot[self.rootdir, 'sh', '/tmp/tag-script'])

    def runPostScript(self, command):
        self.run(chroot[self.rootdir, 'sh', '-c', command])

    def createInitrd(self):
        initrd = '/boot/initrd-%s' % self.kver
        self.run(chroot[self.rootdir,
             'depmod', '-ae', '-F', '/boot/System.map-' + self.kver, self.kver],
             fg=True)
        # --add-drivers raid0 raid1 raid4 raid5 raid6 raid10 ...?
        self.run(chroot[self.rootdir,
             'dracut', '-f', initrd, self.kver],
             fg=True)

    def runBootman(self):
        rootConf = self.rootdir + '/etc/bootloader.d/root.conf'
        if not os.path.exists(rootConf):
            file(rootConf, 'w').write('\n'.join((
                'timeout 50',
                'read_only ',
                'root LABEL=/',
                '')))

        self.run(chroot[self.rootdir, 'bootman'])

        # make images work when booted in EC2
        menuLst = self.rootdir + '/boot/grub/menu.lst'
        grubConf = self.rootdir + '/boot/grub/grub.conf'
        if os.path.exists(grubConf) and not os.path.exists(menuLst):
            file(menuLst, 'w').write(
                file(grubConf).read(
                    ).replace('    kernel',
                              '    root (hd0)\n    kernel').replace(
                              'timeout=5',
                              'timeout=1'
                              ))
