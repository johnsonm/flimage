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
import stat
import subprocess
import sys
import tempfile

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

    def Popen(self, arglist, **kwargs):
        if 'stderr' not in kwargs:
            kwargs['stderr'] = self.errfd
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        sys.stderr.write('running command "%s"' % ' '.join(arglist))
        cmd = arglist[0]
        if cmd == 'chroot' and len(arglist) > 2:
            cmd = arglist[2]
        self.progress('%s ...' % cmd)
        return subprocess.Popen(arglist, **kwargs)

    def wait(self, p):
        ret = p.wait()
        if ret:
            self.raiseError, 'command failed with return code %d' % ret

    def PopenWait(self, arglist, **kwargs):
        p = self.Popen(arglist, **kwargs)
        self.wait(p)

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
            self.PopenWait(
                ['dd', 'if=/dev/zero', 'of=%s'%self.image, 'bs=1M',
                 'seek=%d' %(self.size), 'count=0', ])
        else:
            self.PopenWait(
                ['dd', 'if=/dev/zero', 'of=%s'%self.image, 'bs=1M',
                 'count=%d' %self.size, ])

    def partitionImage(self, size):
        sectors = size * 2048
        firstsector = 2048 # use fdisk default of reserving 1MB
        lastsector = sectors - 1
        return self.PopenWait(['parted', '--script', self.image,
            'unit', 's',
            'mklabel', 'msdos',
            'mkpart', 'primary', '%d'%firstsector, '%d'%lastsector,
            'set', '1', 'boot', 'on'])

    def createFilesystem(self):
        return self.PopenWait(['mkfs.%s' %self.fstype, '-F', '-L', '/', self.image])

    def loopImage(self):
        p = self.Popen(['kpartx', '-a', '-v', self.image],
            stdout=subprocess.PIPE)
        o, e = p.communicate()
        lines = o.split('\n')
        self.wait(p)
        if lines:
            self.mountDevice = '/dev/mapper/%s' %(
                [x.split()[2] for x in lines if x][0])

    def unloopImage(self):
        self.PopenWait(['kpartx', '-d', self.image])

    def mountFilesystem(self):
        self.rootdir = tempfile.mkdtemp(prefix='mkd.', dir=self.basedir)
        self.PopenWait(['mount', self.mountDevice, '-t', self.fstype, self.rootdir])
        
    def unmountFilesystem(self):
        self.PopenWait(['umount', self.rootdir])

    def prepareFilesystem(self, modelFile):
        os.mkdir(self.rootdir + '/dev', 0755)
        os.mknod(self.rootdir + '/dev/null',  0666|stat.S_IFCHR, os.makedev(1,3))
        os.mknod(self.rootdir + '/dev/zero',  0666|stat.S_IFCHR, os.makedev(1,5))
        os.mknod(self.rootdir + '/dev/full',  0666|stat.S_IFCHR, os.makedev(1,7))
        os.mknod(self.rootdir + '/dev/random',  0666|stat.S_IFCHR, os.makedev(1,8))
        os.mknod(self.rootdir + '/dev/urandom',  0666|stat.S_IFCHR, os.makedev(1,9))
        os.mknod(self.rootdir + '/dev/console',  0600|stat.S_IFCHR, os.makedev(5,1))

        os.mkdir(self.rootdir + '/dev/shm', 2777)
        os.mkdir(self.rootdir + '/dev/pts', 0755)
        os.mkdir(self.rootdir + '/tmp', 2777)
        os.mkdir(self.rootdir + '/etc', 0755)
        os.mkdir(self.rootdir + '/etc/conary', 0755)
        os.mkdir(self.rootdir + '/etc/sysconfig', 0755)
        os.mkdir(self.rootdir + '/proc', 0755)
        os.mkdir(self.rootdir + '/sys', 0755)
        os.mkdir(self.rootdir + '/var', 0755)
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
        file(self.rootdir + '/etc/conary/system-model', 'w+').write(
            file(modelFile).read())
        file(self.rootdir + '/etc/sysconfig/i18n', 'w+').write('\n'.join((
            'LANG="en_US.UTF-8"',
            'SYSFONT="latarcyrheb-sun16"',
            '',
        )))

        self.PopenWait(['mount', 'proc', '-t', 'proc', self.rootdir + '/proc'])
        self.PopenWait(['mount', 'devpts', '-t', 'devpts',
                        self.rootdir + '/dev/pts', '-o', 'gid=5,mode=620'])
        self.PopenWait(['mount', 'sys', '-t', 'sysfs', self.rootdir + '/sys'])
        self.PopenWait(['mount', 'tmpfs', '-t', 'tmpfs', self.rootdir + '/dev/shm'])
        self.PopenWait(['mount', 'tmpfs', '-t', 'tmpfs', self.rootdir + '/tmp'])
        # speed up database by not waiting for disk
        self.PopenWait(['mount', 'tmpfs', '-t', 'tmpfs',
                        self.rootdir + '/var/lib/conarydb'])


    def finishFilesystem(self):
        mbr = None
        if os.path.exists(self.rootdir + '/boot/extlinux/mbr.bin'):
            mbr = file(self.rootdir + '/boot/extlinux/mbr.bin').read()

            self.PopenWait(['extlinux', '-i', self.rootdir + '/boot/extlinux'])

        # copy conary database from tmpfs to image
        os.mkdir(self.rootdir + '/var/lib/conarydb.real', 0755)
        conarydbFiles = [self.rootdir + '/var/lib/conarydb/' + x
                         for x in os.listdir(self.rootdir + '/var/lib/conarydb')]
        for conaryFile in conarydbFiles:
            self.PopenWait(['cp', '-a',
                            conaryFile,
                            self.rootdir + '/var/lib/conarydb.real/'])
        self.PopenWait(['umount', self.rootdir + '/var/lib/conarydb'])
        self.unmountConarydb()
        os.rename(self.rootdir + '/var/lib/conarydb.real',
                  self.rootdir + '/var/lib/conarydb')


        self.unmountFilesystems()

        if mbr:
            f = os.open(self.image, os.O_WRONLY)
            l = os.write(f, mbr)
            os.close(f)
            if l != len(mbr):
                raiseError('failed to write full MBR: wrote %d of %d bytes'
                           % (l, len(mbr)))

    def unmountConarydb(self):
        self.PopenWait(['umount', self.rootdir + '/var/lib/conarydb'])

    def unmountFilesystems(self):
        self.PopenWait(['umount', self.rootdir + '/proc'])
        self.PopenWait(['umount', self.rootdir + '/dev/pts'])
        self.PopenWait(['umount', self.rootdir + '/sys'])
        self.PopenWait(['umount', self.rootdir + '/dev/shm'])
        self.PopenWait(['umount', self.rootdir + '/tmp'])

    def createTarball(self):
        fd, t = tempfile.mkstemp(prefix='image.',
                                 suffix='.tar.gz',
                                 dir=self.basedir)
        os.close(fd)
        self.PopenWait(['tar', '-C', self.rootdir, '-c', '-z', '-f', t, '.'])
        return t

    def installTarball(self, prefix, tarball):
        basedir = self.rootdir + prefix
        if not os.path.exists(basedir):
            os.makedirs(basedir, mode=0755)
        self.PopenWait(['tar', '-C', basedir, '-x', '-z', '-f', tarball])

    def installTarballWithPrefix(self, tarball):
        prefix = '/'
        if ':' in tarball:
            prefix, tarball = post_image.split(':', 1)
        self.installTarball(prefix, tarball)

    def installPreImage(self, pre_image):
        if pre_image:
            self.installTarballWithPrefix(pre_image)

    def installSystem(self):
        # Note that system config is applied; this is generally not
        # important but may cause :supdoc noise later on (for instance).
        # This can be improved later
        self.PopenWait(
            ['conary', 'sync',
             '--no-interactive',
             '--replace-unmanaged-files',
             '--tag-script=%s/tmp/tag-script' %self.rootdir,
             '--root', self.rootdir],
            stdout=sys.stdout)

    def removeRollbacks(self):
        # remove conary rollbacks to avoid rolling back to uninstalled
        self.PopenWait(
            ['conary', 'rmrollback', 'r.0',
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
            'root %s' % self.rootdev,
            "include '/etc/bootloader.d/*'",
            "linux %s 'Linux %s' /boot/vmlinuz-%s /boot/initrd-%s" %((self.kver,) * 4),
            ''
        )))

    def convertPasswords(self):
        self.PopenWait(
            ['chroot', self.rootdir,
             'pwconv',])

    def unsetRootPassword(self):
        self.PopenWait(
            ['chroot', self.rootdir,
             'usermod', '-p', '', 'root'])

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
        self.PopenWait(
            ['chroot', self.rootdir,
             'sh', '/tmp/tag-script'], stdout=sys.stdout)

    def createInitrd(self):
        initrd = '/boot/initrd-%s' % self.kver
        self.PopenWait(
            ['chroot', self.rootdir,
             'depmod', '-ae', '-F', '/boot/System.map-' + self.kver, self.kver],
            stdout=sys.stdout)
        self.PopenWait(
            ['chroot', self.rootdir,
             'dracut', '-f', initrd, self.kver],
            stdout=sys.stdout)

    def runBootman(self):
        rootConf = self.rootdir + '/etc/bootloader.d/root.conf'
        if not os.path.exists(rootConf):
            file(rootConf, 'w').write('\n'.join((
                'timeout 50',
                'read_only ',
                'root %s' % self.rootdev)))

        self.PopenWait(
            ['chroot', self.rootdir,
             'bootman'])

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
