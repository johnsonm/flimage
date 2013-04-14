Foresight Linux Image Generation
================================

This script builds images for Foresight Linux and Foresight Linux
derivatives.  Inasmuch as it is tested, it is tested only on
Foresight Linux and is specific to Foresight Linux.  Even there,
it is very incomplete.

Features
--------

### Image types ###

* raw filesystem images

* raw hard drive images

* raw images configured to be built into AMIs for EC2

When building any of those images, it can also optionally write out
a tarball of the contents of the image.

You can use qemu-img to convert the hard drive images to other image
types.


### Capabilities ###

* It can lay down an archive of contents that you want in the system
  image before Conary starts.  (This can be used for /etc/passwd and
  /etc/group, to keep user ids in sync between systems.  See the
  included `authpre` script for creating these passwd and group files.)

* It can lay down archives of content after installing with Conary.
  (This can be used for things like pre-populated home directories
  that might conveniently be an image but should not be under Conary
  control, or for Conary repository permissions that should apply
  to the image but not be packaged in a repository.)

* It can run arbitrary commands within the image after installation.
  (For example, this might modify a configuration file or run
  chkconfig to change whether an init script starts by default.)

* It allows you to choose whether to reset the root password
  in the image.

* It allows you to choose the default initlevel.

* If you are building multiple images from the same model, you can
  give it a directory in which to store model-cache files that allow
  Conary to get started building additional images quicker.

It has many limitations, some of which are known.  Some of the known
limitations are documented in issues at github:
https://github.com/johnsonm/flimage/issues


Running
-------

Run `flimage --help` for a summary of the command-line arguments.


Contributing
------------

Filing issues at https://github.com/johnsonm/flimage/issues is a
contribution.

Helping users use this software is a contribution.  Discussion on
using this software should take place on the
foresight-devel@lists.foresightlinux.org mailing list:
https://lists.foresightlinux.org/mailman/listinfo/foresight-devel

Code contributions are accepted under the terms of the Apache License,
version 2.  Where the license requires that "You must cause any
modified files to carry prominent notices stating that You changed
the files", please honor that request with complete and correct
author information in Git commits, rather than in the content of the
file, in order to avoid merge conflicts.

Code contributions should be submitted via a Git pull request.  This
may be a Github pull request, or may be an email containing a reference
to a public Git repository.

This project follows the Linux kernel Developer's Certificate of
Origin 1.1 contributor agreement.  As documented in the Linux Kernel
Documentation/SubmittingPatches document: if you can certify the
below:

    Developer's Certificate of Origin 1.1

    By making a contribution to this project, I certify that:

    (a) The contribution was created in whole or in part by me and I
        have the right to submit it under the open source license
        indicated in the file; or

    (b) The contribution is based upon previous work that, to the best
        of my knowledge, is covered under an appropriate open source
        license and I have the right under that license to submit that
        work with modifications, whether created in whole or in part
        by me, under the same open source license (unless I am
        permitted to submit under a different license), as indicated
        in the file; or

    (c) The contribution was provided directly to me by some other
        person who certified (a), (b) or (c) and I have not modified
        it.

    (d) I understand and agree that this project and the contribution
        are public and that a record of the contribution (including all
        personal information I submit with it, including my sign-off) is
        maintained indefinitely and may be redistributed consistent with
        this project or the open source license(s) involved.

then you just add a line saying

    Signed-off-by: Random J Developer <random@developer.example.org>

using your real name (sorry, no pseudonyms or anonymous contributions.)
