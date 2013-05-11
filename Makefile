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

PYVER=$(shell python -c 'import sys; print(sys.version[0:3])')
export lib = $(shell uname -m | sed -r '/x86_64/{s/.*/lib64/;q};s/.*/lib/')
export prefix = /usr
export bindir = $(prefix)/bin
export libdir = $(prefix)/$(lib)
export libexecdir = $(prefix)/libexec
export sitedir = $(libdir)/python$(PYVER)/site-packages

all:

clean:
	rm -f imagebuilder/*.pyc imagebuilder/*.pyo

install:
	install -d -m 755 $(DESTDIR)$(sitedir)/imagebuilder
	install -m 755 imagebuilder/*.py $(DESTDIR)/$(sitedir)/imagebuilder
	install -d -m 755 $(DESTDIR)$(bindir)
	install -m 755 bin/flimage $(DESTDIR)/$(bindir)/
	install -d -m 755 $(DESTDIR)$(libexecdir)/flimage
	install -m 755 bin/authpre $(DESTDIR)/$(libexecdir)/flimage/
	python -c "from compileall import *; compile_dir('$(DESTDIR)$(sitedir)/imagebuilder', 10, '$(sitedir)/imagebuilder')"
	python -O -c "from compileall import *; compile_dir('$(DESTDIR)$(sitedir)/imagebuilder', 10, '$(sitedir)/imagebuilder')"
