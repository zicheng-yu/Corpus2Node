from __future__ import annotations

import uuid

from corpus2node.core.types import CourseSession
from corpus2node.storage import local


def test_list_session_ids_ignores_orphan_uuid_directories():
    orphan_id = uuid.uuid4()
    local.session_dir(orphan_id)
    session = CourseSession(course_title="valid", lecture_title="valid")
    local.save_session(session)

    assert orphan_id not in local.list_session_ids()
    assert session.session_id in local.list_session_ids()
