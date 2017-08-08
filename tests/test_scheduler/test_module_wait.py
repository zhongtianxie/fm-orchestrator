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

import unittest
import mock
from mock import patch
import module_build_service.messaging
import module_build_service.scheduler.handlers.modules
import modulemd as _modulemd
import os
import vcr
import koji
from tests import conf, db, app, scheduler_init_data
from module_build_service import build_logs
from module_build_service.models import ComponentBuild

base_dir = os.path.dirname(os.path.dirname(__file__))
cassette_dir = base_dir + '/vcr-request-data/'


class TestModuleWait(unittest.TestCase):

    def setUp(self):
        self.config = conf
        self.session = mock.Mock()
        self.fn = module_build_service.scheduler.handlers.modules.wait

        filename = cassette_dir + self.id()
        self.vcr = vcr.use_cassette(filename)
        self.vcr.__enter__()

    def tearDown(self):
        self.vcr.__exit__()
        try:
            path = build_logs.path(1)
            os.remove(path)
        except:
            pass

    @mock.patch('module_build_service.builder.GenericBuilder.create_from_module')
    @mock.patch('module_build_service.models.ModuleBuild.from_module_event')
    @mock.patch('module_build_service.pdc')
    def test_init_basic(self, pdc, from_module_event, create_builder):
        builder = mock.Mock()
        builder.get_disttag_srpm.return_value = 'some srpm disttag'
        builder.build.return_value = 1234, 1, "", None
        builder.module_build_tag = {'name': 'some-tag-build'}
        create_builder.return_value = builder
        mocked_module_build = mock.Mock()
        mocked_module_build.json.return_value = {
            'name': 'foo',
            'stream': 1,
            'version': 1,
            'state': 'some state',
        }

        mmd = _modulemd.ModuleMetadata()
        formatted_testmodule_yml_path = os.path.join(
            base_dir, 'staged_data', 'formatted_testmodule.yaml')
        with open(formatted_testmodule_yml_path, 'r') as f:
            mmd.loads(f)

        mocked_module_build.id = 1
        mocked_module_build.mmd.return_value = mmd
        mocked_module_build.component_builds = []

        from_module_event.return_value = mocked_module_build

        msg = module_build_service.messaging.MBSModule(msg_id=None, module_build_id=1,
                                                       module_build_state='some state')
        self.fn(config=self.config, session=self.session, msg=msg)

    @patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
           return_value={'build': [], 'srpm-build': []})
    @patch("module_build_service.builder.KojiModuleBuilder.get_session")
    @patch("module_build_service.builder.GenericBuilder.create_from_module")
    @patch('module_build_service.pdc')
    def test_new_repo_called_when_macros_reused(
            self, pdc, create_builder, koji_get_session, dbg):
        """
        Test that newRepo is called when module-build-macros build is reused.
        """
        with app.app_context():
            pdc.get_module_tag.return_value = "module-testmodule-master-20170109091357"
            scheduler_init_data()
            koji_session = mock.MagicMock()
            koji_session.newRepo.return_value = 123456
            koji_get_session.return_value = koji_session

            builder = mock.MagicMock()
            builder.koji_session = koji_session
            builder.module_build_tag = {"name": "module-123-build"}
            builder.get_disttag_srpm.return_value = 'some srpm disttag'
            builder.build.return_value = 1234, koji.BUILD_STATES['COMPLETE'], "", "module-build-macros-1-1"
            create_builder.return_value = builder

            msg = module_build_service.messaging.MBSModule(msg_id=None, module_build_id=1,
                                                           module_build_state='some state')
            module_build_service.scheduler.handlers.modules.wait(
                config=conf, session=db.session, msg=msg)
            koji_session.newRepo.assert_called_once_with("module-123-build")

            # When module-build-macros is reused, it still has to appear only
            # once in database.
            builds_count = db.session.query(ComponentBuild).filter_by(
                package="module-build-macros", module_id=1).count()
            self.assertEqual(builds_count, 1)

    @patch("module_build_service.builder.GenericBuilder.default_buildroot_groups",
           return_value={'build': [], 'srpm-build': []})
    @patch("module_build_service.builder.KojiModuleBuilder.get_session")
    @patch("module_build_service.builder.GenericBuilder.create_from_module")
    @patch('module_build_service.pdc')
    def test_new_repo_not_called_when_macros_not_reused(
            self, pdc, create_builder, koji_get_session, dbg):
        """
        Test that newRepo is not called when module-build-macros build is not reused.
        """
        with app.app_context():
            pdc.get_module_tag.return_value = "module-testmodule-master-20170109091357"
            scheduler_init_data()
            koji_session = mock.MagicMock()
            koji_session.newRepo.return_value = 123456
            koji_get_session.return_value = koji_session

            builder = mock.MagicMock()
            builder.koji_session = koji_session
            builder.module_build_tag = {"name": "module-123-build"}
            builder.get_disttag_srpm.return_value = 'some srpm disttag'
            builder.build.return_value = 1234, koji.BUILD_STATES['BUILDING'], "", "module-build-macros-1-1"
            create_builder.return_value = builder

            msg = module_build_service.messaging.MBSModule(msg_id=None, module_build_id=1,
                                                           module_build_state='some state')
            module_build_service.scheduler.handlers.modules.wait(
                config=conf, session=db.session, msg=msg)
            self.assertTrue(not koji_session.newRepo.called)
