# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
import pytest

from mock import call, patch, Mock
from sqlalchemy import func

from module_build_service import conf
from module_build_service.db_session import db_session
from module_build_service.models import BUILD_STATES, ModuleBuild
from module_build_service.scheduler.consumer import MBSConsumer
from module_build_service.scheduler.handlers.greenwave import get_corresponding_module_build
from module_build_service.scheduler.handlers.greenwave import decision_update
from tests import clean_database, make_module_in_db


class TestGetCorrespondingModuleBuild:
    """Test get_corresponding_module_build"""

    def setup_method(self, method):
        clean_database()

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_module_build_nvr_does_not_exist_in_koji(self, ClientSession):
        ClientSession.return_value.getBuild.return_value = None

        assert get_corresponding_module_build("n-v-r") is None

    @pytest.mark.parametrize(
        "build_info",
        [
            # Build info does not have key extra
            {"id": 1000, "name": "ed"},
            # Build info contains key extra, but it is not for the module build
            {"extra": {"submitter": "osbs", "image": {}}},
            # Key module_build_service_id is missing
            {"extra": {"typeinfo": {"module": {}}}},
        ],
    )
    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_cannot_find_module_build_id_from_build_info(self, ClientSession, build_info):
        ClientSession.return_value.getBuild.return_value = build_info

        assert get_corresponding_module_build("n-v-r") is None

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_corresponding_module_build_id_does_not_exist_in_db(self, ClientSession):
        fake_module_build_id, = db_session.query(func.max(ModuleBuild.id)).first()

        ClientSession.return_value.getBuild.return_value = {
            "extra": {"typeinfo": {"module": {"module_build_service_id": fake_module_build_id + 1}}}
        }

        assert get_corresponding_module_build("n-v-r") is None

    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_find_the_module_build(self, ClientSession):
        expected_module_build = (
            db_session.query(ModuleBuild).filter(ModuleBuild.name == "platform").first()
        )

        ClientSession.return_value.getBuild.return_value = {
            "extra": {"typeinfo": {"module": {"module_build_service_id": expected_module_build.id}}}
        }

        build = get_corresponding_module_build("n-v-r")

        assert expected_module_build.id == build.id
        assert expected_module_build.name == build.name


class TestDecisionUpdateHandler:
    """Test handler decision_update"""

    @patch("module_build_service.scheduler.handlers.greenwave.log")
    def test_decision_context_is_not_match(self, log):
        msg = Mock(msg_id="msg-id-1", decision_context="bodhi_update_push_testing")
        decision_update(conf, msg)
        log.debug.assert_called_once_with(
            'Skip Greenwave message %s as MBS only handles messages with the decision context "%s"',
            "msg-id-1",
            "test_dec_context"
        )

    @patch("module_build_service.scheduler.handlers.greenwave.log")
    def test_not_satisfy_policies(self, log):
        msg = Mock(
            msg_id="msg-id-1",
            decision_context="test_dec_context",
            policies_satisfied=False,
            subject_identifier="pkg-0.1-1.c1",
        )
        decision_update(conf, msg)
        log.debug.assert_called_once_with(
            "Skip to handle module build %s because it has not satisfied Greenwave policies.",
            msg.subject_identifier,
        )

    @patch("module_build_service.messaging.publish")
    @patch("module_build_service.builder.KojiModuleBuilder.KojiClientSession")
    def test_transform_from_done_to_ready(self, ClientSession, publish):
        clean_database()

        # This build should be queried and transformed to ready state
        module_build = make_module_in_db(
            "pkg:0.1:1:c1",
            [
                {
                    "requires": {"platform": ["el8"]},
                    "buildrequires": {"platform": ["el8"]},
                }
            ],
        )
        module_build.transition(
            db_session, conf, BUILD_STATES["done"], "Move to done directly for running test."
        )
        db_session.commit()

        # Assert this call below
        first_publish_call = call(
            service="mbs",
            topic="module.state.change",
            msg=module_build.json(db_session, show_tasks=False),
            conf=conf,
        )

        ClientSession.return_value.getBuild.return_value = {
            "extra": {"typeinfo": {"module": {"module_build_service_id": module_build.id}}}
        }

        msg = {
            "msg_id": "msg-id-1",
            "topic": "org.fedoraproject.prod.greenwave.decision.update",
            "msg": {
                "decision_context": "test_dec_context",
                "policies_satisfied": True,
                "subject_identifier": "pkg-0.1-1.c1",
            },
        }
        hub = Mock(config={"validate_signatures": False})
        consumer = MBSConsumer(hub)
        consumer.consume(msg)

        db_session.add(module_build)
        # Load module build again to check its state is moved correctly
        db_session.refresh(module_build)
        assert BUILD_STATES["ready"] == module_build.state

        publish.assert_has_calls([
            first_publish_call,
            call(
                service="mbs",
                topic="module.state.change",
                msg=module_build.json(db_session, show_tasks=False),
                conf=conf,
            ),
        ])
