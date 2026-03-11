ROLE_ORG_ADMIN = "org_admin"
ROLE_WORKSPACE_ADMIN = "workspace_admin"
ROLE_IPR_EDITOR = "ipr_editor"
ROLE_VIEWER = "viewer"

ALL_ROLES = {ROLE_ORG_ADMIN, ROLE_WORKSPACE_ADMIN, ROLE_IPR_EDITOR, ROLE_VIEWER}


def has_role(user_roles, required_roles) -> bool:
    if not user_roles:
        return False
    return bool(set(user_roles) & set(required_roles))
