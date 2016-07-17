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

import rida.scheduler.handlers.repos


class TestRepoDone(unittest.TestCase):

    def setUp(self):
        self.config = mock.Mock()
        self.config.rpms_default_repository = 'dist_git_url'
        self.config.koji_profile = 'staging'  # TODO - point at a fake test config

        self.session = mock.Mock()
        self.fn = rida.scheduler.handlers.repos.done

    @mock.patch('rida.database.ModuleBuild.get_active_by_koji_tag')
    def test_no_match(self, get_active_by_koji_tag):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        get_active_by_koji_tag.return_value = None
        msg = {
            'topic': 'org.fedoraproject.prod.buildsys.repo.done',
            'msg': {'tag': 'no matches for this...'},
        }
        self.fn(config=self.config, session=self.session, msg=msg)

    @mock.patch('rida.builder.KojiModuleBuilder.build')
    @mock.patch('rida.builder.KojiModuleBuilder.buildroot_resume')
    @mock.patch('rida.database.ModuleBuild.get_active_by_koji_tag')
    def test_a_single_match(self, get_active_by_koji_tag, resume, build_fn):
        """ Test that when a repo msg hits us and we have no match,
        that we do nothing gracefully.
        """
        component_build = mock.Mock()
        component_build.package = 'foo'
        component_build.gitref = 'beef'
        component_build.state = None
        module_build = mock.Mock()
        module_build.component_builds = [component_build]

        get_active_by_koji_tag.return_value = module_build
        msg = {
            'topic': 'org.fedoraproject.prod.buildsys.repo.done',
            'msg': {'tag': 'no matches for this...'},
        }
        self.fn(config=self.config, session=self.session, msg=msg)
        build_fn.assert_called_once_with('TODO', 'dist_git_url/rpms/foo?#beef')
