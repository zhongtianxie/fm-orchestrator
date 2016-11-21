# Copyright (c) 2016  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Ralph Bean <rbean@redhat.com>

import os

import modulemd
from datetime import datetime
from module_build_service import app, db
from module_build_service.config import from_app_config
from module_build_service.models import ModuleBuild, BUILD_STATES

app.config.from_object('config.TestConfiguration')
conf = from_app_config()

datadir = os.path.dirname(__file__) + '/data/'


def module_build_from_modulemd(yaml):
    mmd = modulemd.ModuleMetadata()
    mmd.loads(yaml)

    build = ModuleBuild()
    build.name = mmd.name
    build.stream = mmd.stream
    build.version = mmd.version
    build.state = BUILD_STATES['ready']
    build.modulemd = yaml
    build.koji_tag = None
    build.batch = 0
    build.owner = 'some_other_user'
    build.time_submitted = datetime(2016, 9, 3, 12, 28, 33)
    build.time_modified = datetime(2016, 9, 3, 12, 28, 40)
    build.time_completed = None
    return build


def init_data():
    db.session.remove()
    db.drop_all()
    db.create_all()
    for filename in os.listdir(datadir):
        with open(datadir + filename, 'r') as f:
            yaml = f.read()
        build = module_build_from_modulemd(yaml)
        db.session.add(build)
    db.session.commit()
