"""Focus mode: advertised permissions must match focused enforcement.

When a focus folder is active (X-Focus-Folder-Id header, propagated through
focus_folder_id_var), the IAM engine vetoes any folder outside the focus
subtree. These tests check that the permissions *advertised* to the frontend
(get_permissions, get_permissions_per_folder, /api/iam/current-user/) shrink
consistently, so the UI can hide what cannot be managed while focused.
"""

import pytest
from knox.models import AuthToken
from rest_framework.test import APIClient

from core.context import focus_folder_id_var
from core.utils import RoleCodename
from global_settings.models import GlobalSettings
from iam.models import Folder, Role, RoleAssignment, User, UserGroup


@pytest.fixture(autouse=True)
def reset_focus_var():
    """The contextvar survives across tests in the same thread: always reset."""
    token = focus_folder_id_var.set(None)
    yield
    focus_folder_id_var.reset(token)


@pytest.fixture
def admin_user(app_config):
    admin = User.objects.create_superuser("focus-admin@tests.com", is_published=True)
    admin_group = UserGroup.objects.get(name="BI-UG-ADM")
    admin.folder = admin_group.folder
    admin.save()
    admin_group.user_set.add(admin)
    return admin


def _domain(name):
    return Folder.objects.create(
        name=name,
        parent_folder=Folder.get_root_folder(),
        content_type=Folder.ContentType.DOMAIN,
    )


def _client_for(user):
    client = APIClient()
    _, token = AuthToken.objects.create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return client


def _enable_focus_mode_ff():
    ff, _ = GlobalSettings.objects.get_or_create(
        name=GlobalSettings.Names.FEATURE_FLAGS
    )
    ff.value = {**(ff.value or {}), "focus_mode": True}
    ff.save()


@pytest.mark.django_db
class TestFocusScopedPermissionAdvertisement:
    def test_per_folder_permissions_drop_root_and_siblings_under_focus(
        self, admin_user
    ):
        root = Folder.get_root_folder()
        domain_a = _domain("Focus A")
        domain_b = _domain("Focus B")

        unfocused = RoleAssignment.get_permissions_per_folder(
            admin_user, recursive=True
        )
        assert str(root.id) in unfocused
        assert str(domain_a.id) in unfocused
        assert str(domain_b.id) in unfocused

        focus_folder_id_var.set(domain_a.id)
        focused = RoleAssignment.get_permissions_per_folder(admin_user, recursive=True)
        assert str(root.id) not in focused
        assert str(domain_b.id) not in focused
        # role permissions themselves are not folder-typed: the admin role
        # still carries add_user, it is the root folder key that disappears
        assert "add_user" in focused[str(domain_a.id)]

    def test_flat_permissions_drop_out_of_focus_assignments(self, admin_user):
        domain_a = _domain("Focus A")
        domain_b = _domain("Focus B")
        reader = User.objects.create_user("focus-reader@tests.com", is_published=True)
        ra = RoleAssignment.objects.create(
            user=reader,
            role=Role.objects.get(name=RoleCodename.READER.value),
            folder=Folder.get_root_folder(),
            is_recursive=False,
        )
        ra.perimeter_folders.add(domain_b)

        assert RoleAssignment.get_permissions(reader) != {}

        focus_folder_id_var.set(domain_a.id)
        # the reader's only assignment lives outside the focus subtree
        assert RoleAssignment.get_permissions(reader) == {}
        # the admin's recursive root assignment reaches into the focus subtree
        assert "add_user" in RoleAssignment.get_permissions(admin_user)

        focus_folder_id_var.set(domain_b.id)
        assert RoleAssignment.get_permissions(reader) != {}

    def test_group_permissions_are_focus_scoped(self, admin_user):
        domain_a = _domain("Focus A")
        domain_b = _domain("Focus B")
        group = UserGroup.objects.create(
            name="focus-test-group",
            folder=Folder.get_root_folder(),
            is_published=True,
        )
        ra = RoleAssignment.objects.create(
            user_group=group,
            role=Role.objects.get(name=RoleCodename.READER.value),
            folder=Folder.get_root_folder(),
            is_recursive=False,
        )
        ra.perimeter_folders.add(domain_b)

        unfocused = RoleAssignment.get_permissions_per_folder(group, recursive=True)
        assert str(domain_b.id) in unfocused
        assert RoleAssignment.get_permissions(group) != {}

        focus_folder_id_var.set(domain_a.id)
        assert RoleAssignment.get_permissions_per_folder(group, recursive=True) == {}
        assert RoleAssignment.get_permissions(group) == {}

        focus_folder_id_var.set(domain_b.id)
        assert str(domain_b.id) in RoleAssignment.get_permissions_per_folder(
            group, recursive=True
        )
        assert RoleAssignment.get_permissions(group) != {}

    def test_get_editors_ignores_focus_for_license_accounting(self, admin_user):
        domain_a = _domain("Focus A")
        domain_b = _domain("Focus B")
        editor = User.objects.create_user("focus-editor@tests.com", is_published=True)
        ra = RoleAssignment.objects.create(
            user=editor,
            role=Role.objects.get(name=RoleCodename.DOMAIN_MANAGER.value),
            folder=Folder.get_root_folder(),
            is_recursive=False,
        )
        ra.perimeter_folders.add(domain_b)

        unfocused_editor_ids = {user.id for user in User.get_editors()}
        assert editor.id in unfocused_editor_ids

        focus_folder_id_var.set(domain_a.id)
        focused_editor_ids = {user.id for user in User.get_editors()}
        assert focused_editor_ids == unfocused_editor_ids


@pytest.mark.django_db
class TestCurrentUserFocusScoping:
    def test_current_user_reflects_focus(self, admin_user):
        _enable_focus_mode_ff()
        root = Folder.get_root_folder()
        domain_a = _domain("Focus A")
        domain_b = _domain("Focus B")
        client = _client_for(admin_user)

        res = client.get("/api/iam/current-user/")
        assert res.status_code == 200
        body = res.json()
        assert body["focus_folder_id"] is None
        assert str(root.id) in body["domain_permissions"]
        assert {str(domain_a.id), str(domain_b.id)} <= set(body["accessible_domains"])

        res = client.get(
            "/api/iam/current-user/", HTTP_X_FOCUS_FOLDER_ID=str(domain_a.id)
        )
        assert res.status_code == 200
        body = res.json()
        assert body["focus_folder_id"] == str(domain_a.id)
        assert str(root.id) not in body["domain_permissions"]
        assert str(domain_a.id) in body["domain_permissions"]
        assert str(domain_b.id) not in body["domain_permissions"]
        assert body["accessible_domains"] == [str(domain_a.id)]

    def test_focus_header_ignored_when_ff_disabled(self, admin_user):
        root = Folder.get_root_folder()
        domain_a = _domain("Focus A")
        client = _client_for(admin_user)

        res = client.get(
            "/api/iam/current-user/", HTTP_X_FOCUS_FOLDER_ID=str(domain_a.id)
        )
        assert res.status_code == 200
        body = res.json()
        assert body["focus_folder_id"] is None
        assert str(root.id) in body["domain_permissions"]
