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
import stat
import subprocess
import sys
import tempfile

from plumbum import FG, BG, local
from plumbum.cmd import bootman, chroot, conary, cp, dd, depmod, dracut
from plumbum.cmd import extlinux, kpartx, mount, parted, sh, tar, umount
from plumbum.cmd import echo, sqlite3

class ImageBuilderError(IOError):
    pass

class ImageBuilder(object):

    def __init__(self, basedir, size, rootdev, fstype):
        self.basedir = basedir
        self.size = size
        self.rootdev = rootdev
        self.fstype = fstype
        self.errfd, self.errname = tempfile.mkstemp(prefix='mke.',
                                                    suffix='.log',
                                                    dir=basedir)
        self.progressMessage = ''
        fd, self.image = tempfile.mkstemp(prefix='mki.',
                                          suffix='.img',
                                          dir=basedir)
        self.mountDevice = self.image
        self.conaryDbMounted = False
        os.close(fd)
        self.rootdir = None

    def removeRootdir(self):
        if self.rootdir is not None:
            os.rmdir(self.rootdir)

    def cleanUp(self):
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
        sys.stderr.write(file(self.errname).readlines()[-10:])
        raise ImageBuilderError, message

    def run(self, cmd, fg=False):
        os.write(self.errfd, 'RUNNING COMMAND: "%s"\n' % str(cmd))
        if fg:
            sys.stdout.write('\n' + str(cmd) + '\n')
            self.progressMessage = ''
            cmd(stdout=None, stderr=self.errfd)
        else:
            self.progress(str(cmd))
            return cmd(stderr=self.errfd)

    def progress(self, message):
        whiteoutLen = (len(self.progressMessage) - len(message))
        if whiteoutLen > 0:
            whiteout = ' ' * whiteoutLen
        else:
            whiteout = ''
        sys.stderr.write('\r%s%s' %(message, whiteout))
        sys.stderr.flush()
        self.progressMessage = message

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
        lastsector = sectors - 1
        self.run(parted['--script', self.image,
            'unit', 's',
            'mklabel', 'msdos',
            'mkpart', 'primary', '%d'%firstsector, '%d'%lastsector,
            'set', '1', 'boot', 'on'])

    def loopImage(self):
        lines = self.run(kpartx['-a', '-v', self.image]).split('\n')
        if lines:
            self.mountDevice = '/dev/mapper/%s' %(
                [x.split()[2] for x in lines if x][0])
            return [self.mountDevice]
        return []

    def createFilesystem(self):
        return self.run(local['mkfs.%s' %self.fstype]['-F', '-L', '/', self.mountDevice])

    def unloopImage(self):
        self.run(kpartx['-d', self.image])

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
        if os.path.exists(self.rootdir + '/boot/extlinux/mbr.bin'):
            mbr = file(self.rootdir + '/boot/extlinux/mbr.bin').read()

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
        self.run(chroot[self.rootdir, 'usermod', '-p', '""', 'root'])

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
        self.run(chroot[self.rootdir, 'sh', '/tmp/tag-script'], fg=True)

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
                'root LABEL=/')))

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
