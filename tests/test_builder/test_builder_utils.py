# Copyright (c) 2017  Red Hat, Inc.
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
# Written by Matt Prahl <mprahl@redhat.com>

import unittest
import tempfile
import shutil

from mock import patch, Mock, call

from module_build_service.builder import utils
from tests import conf


class TestBuilderUtils(unittest.TestCase):

    @patch('requests.get')
    @patch('koji.ClientSession')
    @patch('module_build_service.builder.utils.execute_cmd')
    def test_create_local_repo_from_koji_tag(self, mock_exec_cmd, mock_koji_session, mock_get):
        session = Mock()
        rpms = [
            {
                'arch': 'src',
                'build_id': 875991,
                'name': 'module-build-macros',
                'release': '1.module_92011fe6',
                'size': 6890,
                'version': '0.1'
            },
            {
                'arch': 'noarch',
                'build_id': 875991,
                'name': 'module-build-macros',
                'release': '1.module_92011fe6',
                'size': 6890,
                'version': '0.1'
            },
            {
                'arch': 'x86_64',
                'build_id': 875636,
                'name': 'ed-debuginfo',
                'release': '2.module_bd6e0eb1',
                'size': 81438,
                'version': '1.14.1'
            },
            {
                'arch': 'x86_64',
                'build_id': 875636,
                'name': 'ed',
                'release': '2.module_bd6e0eb1',
                'size': 80438,
                'version': '1.14.1'
            },
            {
                'arch': 'x86_64',
                'build_id': 875640,
                'name': 'mksh-debuginfo',
                'release': '2.module_bd6e0eb1',
                'size': 578774,
                'version': '54'
            },
            {
                'arch': 'x86_64',
                'build_id': 875640,
                'name': 'mksh',
                'release': '2.module_bd6e0eb1',
                'size': 267042,
                'version': '54'
            }
        ]

        builds = [
            {
                'build_id': 875640,
                'name': 'mksh',
                'release': '2.module_bd6e0eb1',
                'version': '54',
                'volume_name': 'prod'
            },
            {
                'build_id': 875636,
                'name': 'ed',
                'release': '2.module_bd6e0eb1',
                'version': '1.14.1',
                'volume_name': 'prod'
            },
            {
                'build_id': 875991,
                'name': 'module-build-macros',
                'release': '1.module_92011fe6',
                'version': '0.1',
                'volume_name': 'prod'
            }
        ]

        session.listTaggedRPMS.return_value = (rpms, builds)
        session.opts = {'topurl': 'https://kojipkgs.stg.fedoraproject.org/'}
        mock_koji_session.return_value = session

        tag = 'module-testmodule-master-20170405123740-build'
        temp_dir = tempfile.mkdtemp()
        try:
            utils.create_local_repo_from_koji_tag(conf, tag, temp_dir)
        finally:
            shutil.rmtree(temp_dir)

        url_one = ('https://kojipkgs.stg.fedoraproject.org//vol/prod/packages/module-build-macros/'
                   '0.1/1.module_92011fe6/noarch/module-build-macros-0.1-1.module_92011fe6.noarch.'
                   'rpm')
        url_two = ('https://kojipkgs.stg.fedoraproject.org//vol/prod/packages/ed/1.14.1/'
                   '2.module_bd6e0eb1/x86_64/ed-1.14.1-2.module_bd6e0eb1.x86_64.rpm')
        url_three = ('https://kojipkgs.stg.fedoraproject.org//vol/prod/packages/mksh/54/'
                     '2.module_bd6e0eb1/x86_64/mksh-54-2.module_bd6e0eb1.x86_64.rpm')

        expected_calls = [
            call(url_one, stream=True, timeout=60),
            call(url_two, stream=True, timeout=60),
            call(url_three, stream=True, timeout=60)
        ]
        for expected_call in expected_calls:
            self.assertIn(expected_call, mock_get.call_args_list)
        self.assertEqual(len(mock_get.call_args_list), len(expected_calls))