# Copyright (c) 2019  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

import pytest
from mock import patch
from datetime import datetime

import module_build_service.resolver as mbs_resolver
from module_build_service.utils.general import import_mmd, mmd_to_str, load_mmd
from module_build_service.models import ModuleBuild
import tests


@pytest.mark.usefixtures("reuse_component_init_data")
class TestLocalResolverModule:

    def _create_test_modules(self, db_session, koji_tag_with_modules="foo-test"):
        mmd = load_mmd(tests.read_staged_data("platform"))
        mmd = mmd.copy(mmd.get_module_name(), "f30.1.3")

        import_mmd(db_session, mmd)
        platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()

        if koji_tag_with_modules:
            platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()
            platform_mmd = platform.mmd()
            platform_xmd = platform_mmd.get_xmd()
            platform_xmd["mbs"]["koji_tag_with_modules"] = koji_tag_with_modules
            platform_mmd.set_xmd(platform_xmd)
            platform.modulemd = mmd_to_str(platform_mmd)

        for context in ["7c29193d", "7c29193e"]:
            mmd = tests.make_module("testmodule:master:20170109091357:" + context)
            build = ModuleBuild(
                name="testmodule",
                stream="master",
                version=20170109091357,
                state=5,
                build_context="dd4de1c346dcf09ce77d38cd4e75094ec1c08ec3",
                runtime_context="ec4de1c346dcf09ce77d38cd4e75094ec1c08ef7",
                context=context,
                koji_tag="module-testmodule-master-20170109091357-" + context,
                scmurl="https://src.stg.fedoraproject.org/modules/testmodule.git?#ff1ea79",
                batch=3,
                owner="Dr. Pepper",
                time_submitted=datetime(2018, 11, 15, 16, 8, 18),
                time_modified=datetime(2018, 11, 15, 16, 19, 35),
                rebuild_strategy="changed-and-after",
                modulemd=mmd_to_str(mmd),
            )
            build.buildrequires.append(platform)
            db_session.add(build)
        db_session.commit()

    def test_get_buildrequired_modulemds_fallback_to_db_resolver(self, db_session):
        self._create_test_modules(db_session, koji_tag_with_modules=None)
        platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()

        resolver = mbs_resolver.GenericResolver.create(db_session, tests.conf, backend="koji")
        result = resolver.get_buildrequired_modulemds("testmodule", "master", platform.mmd())

        nsvcs = {m.get_nsvc() for m in result}
        assert nsvcs == {
            "testmodule:master:20170109091357:7c29193d",
            "testmodule:master:20170109091357:7c29193e"}

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_get_buildrequired_modulemds_name_not_tagged(self, ClientSession, db_session):
        koji_session = ClientSession.return_value
        koji_session.getLastEvent.return_value = {"id": 123}

        # No package with such name tagged.
        koji_session.listTagged.return_value = []

        self._create_test_modules(db_session)
        platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()
        resolver = mbs_resolver.GenericResolver.create(db_session, tests.conf, backend="koji")
        result = resolver.get_buildrequired_modulemds("testmodule", "master", platform.mmd())

        assert result == []
        koji_session.listTagged.assert_called_with(
            'foo-test', inherit=True, package='testmodule', type='module', event=123)

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_get_buildrequired_modulemds_multiple_streams(self, ClientSession, db_session):
        koji_session = ClientSession.return_value

        # We will ask for testmodule:master, but there is also testmodule:2 in a tag.
        koji_session.listTagged.return_value = [
            {
                'build_id': 123, 'name': 'testmodule', 'version': '2',
                'release': '820181219174508.9edba152', 'tag_name': 'foo-test'
            },
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20170109091357.7c29193d', 'tag_name': 'foo-test'
            }]

        self._create_test_modules(db_session)
        platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()
        resolver = mbs_resolver.GenericResolver.create(db_session, tests.conf, backend="koji")
        result = resolver.get_buildrequired_modulemds("testmodule", "master", platform.mmd())

        nsvcs = {m.get_nsvc() for m in result}
        assert nsvcs == {"testmodule:master:20170109091357:7c29193d"}

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_get_buildrequired_modulemds_tagged_but_not_in_db(self, ClientSession, db_session):
        koji_session = ClientSession.return_value

        # We will ask for testmodule:2, but it is not in database, so it should raise
        # ValueError later.
        koji_session.listTagged.return_value = [
            {
                'build_id': 123, 'name': 'testmodule', 'version': '2',
                'release': '820181219174508.9edba152', 'tag_name': 'foo-test'
            },
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20170109091357.7c29193d', 'tag_name': 'foo-test'
            }]

        self._create_test_modules(db_session)
        platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()
        resolver = mbs_resolver.GenericResolver.create(db_session, tests.conf, backend="koji")
        expected_error = ("Module testmodule:2:820181219174508:9edba152 is tagged in the "
                          "foo-test Koji tag, but does not exist in MBS DB.")
        with pytest.raises(ValueError, match=expected_error):
            resolver.get_buildrequired_modulemds("testmodule", "2", platform.mmd())

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_get_buildrequired_modulemds_multiple_versions_contexts(
            self, ClientSession, db_session):
        koji_session = ClientSession.return_value

        # We will ask for testmodule:2, but it is not in database, so it should raise
        # ValueError later.
        koji_session.listTagged.return_value = [
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20160110091357.7c29193d', 'tag_name': 'foo-test'
            },
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20170109091357.7c29193d', 'tag_name': 'foo-test'
            },
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20170109091357.7c29193e', 'tag_name': 'foo-test'
            },
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20160109091357.7c29193d', 'tag_name': 'foo-test'
            }]

        self._create_test_modules(db_session)
        platform = db_session.query(ModuleBuild).filter_by(stream="f30.1.3").one()
        resolver = mbs_resolver.GenericResolver.create(db_session, tests.conf, backend="koji")
        result = resolver.get_buildrequired_modulemds("testmodule", "master", platform.mmd())

        nsvcs = {m.get_nsvc() for m in result}
        assert nsvcs == {
            "testmodule:master:20170109091357:7c29193d",
            "testmodule:master:20170109091357:7c29193e"}

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_filter_inherited(self, ClientSession, db_session):
        koji_session = ClientSession.return_value

        koji_session.getFullInheritance.return_value = [
            {"name": "foo-test"},
            {"name": "foo-test-parent"},
        ]

        builds = [
            {
                'build_id': 124, 'name': 'testmodule', 'version': 'master',
                'release': '20170110091357.7c29193d', 'tag_name': 'foo-test'
            },
            {
                'build_id': 125, 'name': 'testmodule', 'version': 'master',
                'release': '20180109091357.7c29193d', 'tag_name': 'foo-test-parent'
            },
            {
                'build_id': 126, 'name': 'testmodule', 'version': '2',
                'release': '20180109091357.7c29193d', 'tag_name': 'foo-test-parent'
            }]

        resolver = mbs_resolver.GenericResolver.create(db_session, tests.conf, backend="koji")
        new_builds = resolver._filter_inherited(koji_session, builds, "foo-test", {"id": 123})

        nvrs = {"{name}-{version}-{release}".format(**b) for b in new_builds}
        assert nvrs == {
            "testmodule-master-20170110091357.7c29193d",
            "testmodule-2-20180109091357.7c29193d"}