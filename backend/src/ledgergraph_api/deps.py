"""Request dependencies: who is calling, and what they may do.

RBAC is enforced in **two** places, deliberately, because the two
questions are different:

* `require_role(...)` answers "may this kind of user do this kind of
  thing" and is a route dependency;
* the material-amount check answers "may this user decide *this* case",
  which depends on the case's own value and therefore cannot live on the
  route.

Only the first is a decorator-shaped problem. Putting the second there
too would mean either duplicating the amount into the URL or checking it
nowhere, and the second is how a ₹5,00,000 adjustment gets approved by
an analyst.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from ledgergraph_domain.enums import UserRole

from .auth import AuthError, read_access_token
from .store import Repository, User, get_repository


def _unauthenticated(code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        # Tells a client *why*, so it can refresh rather than blindly
        # bouncing the user to a login form on an expired token.
        headers={"WWW-Authenticate": f'Bearer error="{code}"'},
    )


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller from a bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthenticated("missing_token", "an access token is required")

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = read_access_token(token)
    except AuthError as exc:
        raise _unauthenticated(exc.code.lower(), str(exc)) from exc

    repo: Repository = get_repository()
    user = await repo.get_user(claims.user_id)
    if user is None:
        # The token is validly signed but names nobody - a deleted user,
        # or a token minted against a different store. Either way it is
        # not an identity.
        raise _unauthenticated("unknown_subject", "token does not identify a user")
    if not user.is_active:
        raise _unauthenticated("account_inactive", "this account is disabled")

    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*allowed: UserRole):
    """Route dependency gating on role.

    The UI hides what a user cannot do; this is what makes that true. A
    hidden button is a convenience, not a control - PRD story F2 is
    explicit that the API must refuse regardless of what the UI showed.
    """
    allowed_set = set(allowed)

    async def dependency(user: CurrentUser) -> User:
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"this action requires one of "
                    f"{sorted(r.value for r in allowed_set)}; you are {user.role.value}"
                ),
            )
        return user

    return dependency


#: Anyone signed in may look. Deciding is separate.
CanRead = Annotated[User, Depends(current_user)]

#: Reviewers and above may decide a case below the material threshold.
CanDecide = Annotated[
    User,
    Depends(require_role(UserRole.REVIEWER, UserRole.CONTROLLER, UserRole.ADMIN)),
]

#: Controllers and above may change policy or decide material cases.
CanControl = Annotated[
    User, Depends(require_role(UserRole.CONTROLLER, UserRole.ADMIN))
]

#: Only an administrator may manage other users and their roles. Kept
#: distinct from CanControl because granting a role is a higher privilege
#: than deciding a case: it is the one action that can create another
#: admin.
CanAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
